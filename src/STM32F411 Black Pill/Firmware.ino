// SPDX-License-Identifier: MIT
// =============================================================================
// Dual MAX30001 – STM32F411 Black Pill – ONBOARD DSP EDITION v7.1
// =============================================================================
// Hardware:
//   MCU  : STM32F411CEU6 Black Pill (Cortex-M4F, 100 MHz, 128 KB RAM)
//   Chip1: CS = PA0  →  ECG1 + BioZ1 (APW1)
//   Chip2: CS = PB0  →  ECG2 + BioZ2 (APW2)
//   SPI1 : SCK=PA5  MISO=PA6  MOSI=PA7
//
// Packet (30 bytes):
//   Header  : 0x0A 0xFA 0x16 0x00 0x02  (DATA_LEN=22)
//   Payload : ECG1[4LE] BZ1[4LE] ECG2[4LE] BZ2[4LE] flags[1] rsvd[5]
//   Footer  : 0x00 0x0B
//   flags   : bit0=R-peak  bit1=APW1-foot  bit2=APW2-foot
// =============================================================================

#include <SPI.h>
#include <protocentral_max30001.h>
#include <math.h>
#include <Wire.h>
#include <Adafruit_INA219.h>

// ── Pins ──────────────────────────────────────────────────────────────────────
#define CS1_PIN  PA0
#define CS2_PIN  PB0

#define MAX30001_SPI_SPEED  1000000UL
#define SAMPLE_RATE         MAX30001_RATE_128
#define FS                  128
#define SAMPLE_PERIOD_MS    8

#define REG_SYNCH     0x09
#define REG_CNFG_GEN  0x10
#define REG_CNFG_BIOZ 0x18
#define WREG 0x00
#define RREG 0x01

// ── Packet ────────────────────────────────────────────────────────────────────
#define PKT_START_1   0x0A
#define PKT_START_2   0xFA
#define PKT_TYPE_DATA 0x02
#define PKT_STOP      0x0B
#define DATA_LEN      29

static const uint8_t PKT_HDR[5] = {PKT_START_1,PKT_START_2,DATA_LEN,0x00,PKT_TYPE_DATA};
static const uint8_t PKT_FTR[2] = {0x00,PKT_STOP};

// INA219 Global Storage
unsigned long lastInaRead = 0;
float last_vbus = 0.0;
float last_current = 0.0;
float last_power = 0.0;

// ── Ring buffer ───────────────────────────────────────────────────────────────
#define RING_SIZE  1024u
#define RING_MASK  (RING_SIZE-1u)

// ── Pan-Tompkins ──────────────────────────────────────────────────────────────
#define PT_REFRACTORY 32
#define PT_MWI_WIN    19
#define PT_THRESH_K   1.5f
#define PT_WARMUP_N   256

// ── APW1 (cubic-poly, ECG-triggered) ─────────────────────────────────────────
#define APW1_WIN_MAX     256
#define APW1_WIN_MIN     32
#define APW1_SEARCH_FRAC 0.50f
#define SEG_COUNT        10
#define MIN_SEG          3
#define MIN_ISECT        4
#define MAX_APW1_JOBS    4

// ── APW2 (Asymmetric Morphological V-Shape) ──────────────────────────────────
#define APW2_WARMUP_N   192
#define APW2_EMA_A      0.015f   
#define APW2_W          12       // 93ms half-window (wider to ignore large notches)
#define APW2_N          25       // 2*W + 1 (187ms full window)
#define APW2_REFRAC     40       // min samples between feet (~310 ms max HR)

// ── Sentinel ──────────────────────────────────────────────────────────────────
#define NO_PENDING 0xFFFFFFFFu

// =============================================================================
// Globals
// =============================================================================

MAX30001 chip1(CS1_PIN);
MAX30001 chip2(CS2_PIN);

Adafruit_INA219 ina219;

bool chip1_ok=false, chip2_ok=false;
bool skip1=false, skip2=false;

int32_t  ecg1_ring[RING_SIZE];
int32_t  bz1_ring [RING_SIZE];
int32_t  bz2_ring [RING_SIZE];
uint32_t ring_head=0;
uint32_t sample_count=0;

float apw1_buf[APW1_WIN_MAX];

// ── Pan-Tompkins state ────────────────────────────────────────────────────────
static float   pt_hp_in=0,pt_hp_out=0,pt_lp=0;
static float   pt_diff[5]={0};
static uint8_t pt_didx=0;
static float   pt_mwi[PT_MWI_WIN]={0};
static uint8_t pt_midx=0;
static float   pt_msum=0,pt_emean=0,pt_esq=0;
static uint16_t pt_warm=0;
static float   pt_mp2=0,pt_mp1=0;
static int32_t pt_refrac=0;

// ── APW1 job queue ────────────────────────────────────────────────────────────
struct Apw1Job { uint32_t win_start; uint32_t beat_len; };
static Apw1Job  apw1_jobs[MAX_APW1_JOBS];
static uint8_t  apw1_jwr=0, apw1_jrd=0;
static uint32_t apw1_prev_rhead=NO_PENDING;
static uint32_t pending_foot1=NO_PENDING;

// ── APW2 Morphological Tracking State ─────────────────────────────────────────
static float    apw2_emean=0.0f;
static float    apw2_evar=0.0f;
static uint16_t apw2_warm=0;
static int32_t  apw2_refrac=0;
static uint32_t pending_foot2=NO_PENDING;

static float    apw2_win[APW2_N]={0};
static uint8_t  apw2_ptr=0;
static float    apw2_lp=0.0f;

// ── Per-sample flags ──────────────────────────────────────────────────────────
static bool flag_rpeak=false, flag_foot1=false, flag_foot2=false;
static unsigned long lastSample=0, lastBanner=0;
static uint32_t pktCount=0;

// =============================================================================
// SPI helpers
// =============================================================================

void writeReg(uint32_t cs, uint8_t addr, uint32_t data){
    uint32_t other=(cs==(uint32_t)CS1_PIN)?(uint32_t)CS2_PIN:(uint32_t)CS1_PIN;
    digitalWrite(other,HIGH);
    SPI.beginTransaction(SPISettings(MAX30001_SPI_SPEED,MSBFIRST,SPI_MODE0));
    digitalWrite(cs,LOW);
    SPI.transfer((addr<<1)|WREG);
    SPI.transfer((data>>16)&0xFF);
    SPI.transfer((data>> 8)&0xFF);
    SPI.transfer( data     &0xFF);
    digitalWrite(cs,HIGH);
    SPI.endTransaction();
}

uint32_t readReg(uint32_t cs, uint8_t addr){
    uint32_t other=(cs==(uint32_t)CS1_PIN)?(uint32_t)CS2_PIN:(uint32_t)CS1_PIN;
    digitalWrite(other,HIGH);
    uint8_t b[3]={0,0,0};
    SPI.beginTransaction(SPISettings(MAX30001_SPI_SPEED,MSBFIRST,SPI_MODE0));
    digitalWrite(cs,LOW);
    SPI.transfer((addr<<1)|RREG);
    b[0]=SPI.transfer(0xFF);
    b[1]=SPI.transfer(0xFF);
    b[2]=SPI.transfer(0xFF);
    digitalWrite(cs,HIGH);
    SPI.endTransaction();
    return ((uint32_t)b[0]<<16)|((uint32_t)b[1]<<8)|b[2];
}

inline void deselectBoth(){
    digitalWrite(CS1_PIN,HIGH);
    digitalWrite(CS2_PIN,HIGH);
}

// =============================================================================
// Chip helpers
// =============================================================================

bool initChip(MAX30001 &chip, uint32_t ownCS, uint32_t otherCS, const char *lbl){
    digitalWrite(otherCS,HIGH); delay(10);
    Serial.print(lbl); Serial.print(F(" begin... "));
    if(chip.begin()!=MAX30001_SUCCESS){Serial.println(F("FAIL(begin)"));return false;}
    if(!chip.isConnected()){Serial.println(F("FAIL(noConn)"));return false;}
    max30001_device_info_t info; chip.getDeviceInfo(&info);
    Serial.print(F("OK PartID=0x")); Serial.print(info.part_id,HEX);
    Serial.print(F(" Rev=0x")); Serial.println(info.revision,HEX);
    return true;
}

void verifyBioZ(uint32_t cs, const char *lbl){
    uint32_t bioz=readReg(cs,REG_CNFG_BIOZ);
    uint32_t gen =readReg(cs,REG_CNFG_GEN);
    Serial.print(lbl);
    Serial.print(F(" CNFG_BIOZ=0x")); Serial.print(bioz,HEX);
    Serial.print(F("  enz_bioz="));
    Serial.println((gen>>19)&1u?F("ON"):F("OFF (warn!)"));
}

// =============================================================================
// Pan-Tompkins  (sample-by-sample, returns true on R-peak)
// =============================================================================

bool pt_push(int32_t raw){
    float x=(float)raw;
    const float AH=0.31831f/(0.31831f+1.0f/FS);
    float hp=AH*(pt_hp_out+x-pt_hp_in);
    pt_hp_in=x; pt_hp_out=hp;
    const float AL=(1.0f/FS)/(0.010610f+1.0f/FS);
    float lp=AL*hp+(1.0f-AL)*pt_lp; pt_lp=lp;
    pt_diff[pt_didx]=lp;
    float d=(2.0f*pt_diff[pt_didx]
            +     pt_diff[(pt_didx+4)%5]
            -     pt_diff[(pt_didx+2)%5]
            -2.0f*pt_diff[(pt_didx+1)%5])*(FS/8.0f);
    pt_didx=(pt_didx+1)%5;
    float sq=d*d;
    pt_msum-=pt_mwi[pt_midx];
    pt_mwi[pt_midx]=sq; pt_msum+=sq;
    pt_midx=(pt_midx+1)%PT_MWI_WIN;
    float mwi=pt_msum/(float)PT_MWI_WIN;
    const float EA=0.01f;
    pt_emean=(1.0f-EA)*pt_emean+EA*mwi;
    pt_esq  =(1.0f-EA)*pt_esq  +EA*mwi*mwi;
    float var=pt_esq-pt_emean*pt_emean;
    if(var<0.0f)var=0.0f;
    float thr=pt_emean+PT_THRESH_K*sqrtf(var);
    if(pt_warm<PT_WARMUP_N) pt_warm++;
    bool peak=false;
    if(pt_warm>=PT_WARMUP_N && pt_refrac<=0){
        if(pt_mp1>pt_mp2 && pt_mp1>mwi && pt_mp1>thr){
            peak=true; pt_refrac=PT_REFRACTORY;
        }
    }
    if(pt_refrac>0) pt_refrac--;
    pt_mp2=pt_mp1; pt_mp1=mwi;
    return peak;
}

// =============================================================================
// APW1 foot detector — cubic-polynomial (Kazanavicius 2005)
// =============================================================================

static void lsq_line(const float *y,int n,int x0,float *a,float *b){
    double sx=0,sy=0,sxx=0,sxy=0;
    for(int i=0;i<n;i++){
        double xi=(double)(i+x0);
        sx+=xi; sy+=(double)y[i]; sxx+=xi*xi; sxy+=xi*(double)y[i];
    }
    double dn=(double)n*sxx-sx*sx;
    if(dn>-1e-12&&dn<1e-12){*b=0.0f;*a=n>0?(float)(sy/n):0.0f;return;}
    *b=(float)(((double)n*sxy-sx*sy)/dn);
    *a=(float)((sy-(double)(*b)*sx)/(double)n);
}

static int gauss4(double M[4][5]){
    for(int c=0;c<4;c++){
        int pr=c; double pv=fabs(M[c][c]);
        for(int r=c+1;r<4;r++) if(fabs(M[r][c])>pv){pv=fabs(M[r][c]);pr=r;}
        if(pr!=c) for(int j=0;j<=4;j++){double t=M[c][j];M[c][j]=M[pr][j];M[pr][j]=t;}
        if(fabs(M[c][c])<1e-14) return 0;
        for(int r=c+1;r<4;r++){
            double f=M[r][c]/M[c][c];
            for(int j=c;j<=4;j++) M[r][j]-=f*M[c][j];
        }
    }
    double cv[4];
    for(int r=3;r>=0;r--){
        double s=M[r][4];
        for(int j=r+1;j<4;j++) s-=M[r][j]*cv[j];
        cv[r]=s/M[r][r];
    }
    for(int r=0;r<4;r++) M[r][4]=cv[r];
    return 1;
}

static int apw1_cubic_foot(int n){
    auto raw_min=[&]()->int{
        int mi=0; float mv=apw1_buf[0];
        for(int i=1;i<n;i++) if(apw1_buf[i]<mv){mv=apw1_buf[i];mi=i;}
        return mi;
    };
    if(n<12) return raw_min();
    int sl=n/SEG_COUNT;
    if(sl<MIN_SEG) return raw_min();

    float ix[SEG_COUNT],ii[SEG_COUNT]; int cnt=0;
    for(int s=0;s<SEG_COUNT-1;s++){
        int s1=s*sl, l1=sl, s2=(s+1)*sl, l2=(s+2==SEG_COUNT)?(n-s2):sl;
        if(l1<MIN_SEG||l2<MIN_SEG) continue;
        float a1,b1,a2,b2;
        lsq_line(apw1_buf+s1,l1,s1,&a1,&b1);
        lsq_line(apw1_buf+s2,l2,s2,&a2,&b2);
        float dn=b1-b2;
        if(fabsf(dn)<1e-9f) continue;
        float xi=(a2-a1)/dn;
        float lo=(float)s1-(float)sl, hi=(float)(s2+l2)+(float)sl;
        if(xi<lo||xi>hi) continue;
        ix[cnt]=xi; ii[cnt]=(float)cnt; cnt++;
    }
    if(cnt<MIN_ISECT) return raw_min();

    double M[4][5]={{0.0}};
    for(int i=0;i<cnt;i++){
        double k=(double)ii[i],y=(double)ix[i];
        double k2=k*k,k3=k2*k,k4=k3*k,k5=k4*k,k6=k5*k;
        M[0][0]+=1;  M[0][1]+=k;  M[0][2]+=k2;M[0][3]+=k3;M[0][4]+=y;
        M[1][0]+=k;  M[1][1]+=k2; M[1][2]+=k3;M[1][3]+=k4;M[1][4]+=k*y;
        M[2][0]+=k2; M[2][1]+=k3; M[2][2]+=k4;M[2][3]+=k5;M[2][4]+=k2*y;
        M[3][0]+=k3; M[3][1]+=k4; M[3][2]+=k5;M[3][3]+=k6;M[3][4]+=k3*y;
    }
    if(!gauss4(M)) return raw_min();

    double c0=M[0][4],c1=M[1][4],c2=M[2][4],c3=M[3][4],best=1e38;
    for(int i=0;i<cnt;i++){
        double t=i,v=c0+c1*t+c2*t*t+c3*t*t*t;
        if(v<best) best=v;
    }
    if(fabs(c3)>1e-14){
        double qa=3.0*c3,qb=2.0*c2,qc=c1,disc=qb*qb-4.0*qa*qc;
        if(disc>=0.0){
            double sq=sqrt(disc);
            for(int k=0;k<2;k++){
                double t=(k==0)?(-qb+sq)/(2.0*qa):(-qb-sq)/(2.0*qa);
                if(t>=0.0&&t<=(double)(cnt-1)){
                    double v=c0+c1*t+c2*t*t+c3*t*t*t;
                    if(v<best) best=v;
                }
            }
        }
    }
    int foot=(int)(best+0.5);
    if(foot<0) foot=0;
    if(foot>=n) foot=n-1;
    return foot;
}

void apw1_run_job(){
    if(apw1_jrd==apw1_jwr) return;
    Apw1Job &j=apw1_jobs[apw1_jrd];
    apw1_jrd=(apw1_jrd+1u)%MAX_APW1_JOBS;

    uint32_t bl=j.beat_len;
    if(bl>(uint32_t)APW1_WIN_MAX) bl=(uint32_t)APW1_WIN_MAX;
    if(bl<(uint32_t)APW1_WIN_MIN) return;

    int srch=(int)((float)bl*APW1_SEARCH_FRAC);
    if(srch<12) srch=(int)bl; 

    for(int i=0;i<srch;i++){
        uint32_t idx=(j.win_start+(uint32_t)i)&RING_MASK;
        apw1_buf[i]=(float)bz1_ring[idx];
    }

    int rel=apw1_cubic_foot(srch);

    uint32_t samples_since=(ring_head-j.win_start)&RING_MASK;
    uint32_t abs_base=sample_count-samples_since;
    pending_foot1=abs_base+(uint32_t)rel;
}

// =============================================================================
// APW2 PIPELINE: Asymmetric Morphological V-Shape Detector (v7.1)
// =============================================================================

void apw2_push(int32_t bz2_raw){
    float x = (float)bz2_raw;

    // 1. INSTANT BASELINE INIT
    if (apw2_warm == 0) {
        apw2_emean = x;
        apw2_evar  = 0.0f;
        apw2_lp    = x;
        for(int i=0; i<APW2_N; i++) apw2_win[i] = x;
        apw2_warm++;
        return;
    }

    // 2. Light quantization smoothing (decreased phase delay from 0.7 to 0.3)
    apw2_lp = 0.3f * apw2_lp + 0.7f * x;

    // 3. Stable Baseline Stats
    float delta = apw2_lp - apw2_emean;
    apw2_emean += APW2_EMA_A * delta;
    apw2_evar = (1.0f - APW2_EMA_A) * apw2_evar + APW2_EMA_A * delta * delta;
    float std_est = sqrtf(apw2_evar);

    // 4. Push into sliding morphological window
    apw2_win[apw2_ptr] = apw2_lp;
    apw2_ptr = (apw2_ptr + 1) % APW2_N;

    if (apw2_warm < APW2_WARMUP_N) {
        apw2_warm++;
        return;
    }
    if (apw2_refrac > 0) apw2_refrac--;

    // 5. Evaluate the EXACT CENTER of the rolling window
    uint8_t mid_idx = (apw2_ptr + APW2_W) % APW2_N;
    float mid_val = apw2_win[mid_idx];

    // Fast fail: Must be deep enough below the mean to be a trough
    if (mid_val > apw2_emean - 0.2f * std_est) return;

    bool is_trough = true;
    float left_max = -1e6f, right_max = -1e6f;

    // 6. Verify strictly lowest point in the expanded neighborhood
    for (int i=1; i<=APW2_W; i++) {
        // Evaluate the Left Side (older samples)
        int idx_L = (mid_idx + APW2_N - i) % APW2_N;
        if (apw2_win[idx_L] < mid_val) { is_trough = false; break; }
        if (apw2_win[idx_L] > left_max) left_max = apw2_win[idx_L];

        // Evaluate the Right Side (newer samples)
        int idx_R = (mid_idx + i) % APW2_N;
        if (apw2_win[idx_R] <= mid_val) { is_trough = false; break; } // <= captures right edge of flat bottom
        if (apw2_win[idx_R] > right_max) right_max = apw2_win[idx_R];
    }

    // 7. ASYMMETRICAL Morphological 'V' Confirmation 
    if (is_trough && apw2_refrac <= 0) {
        // Left side (diastolic run-off) is a slow drop. Right side (systolic upstroke) is a sharp rise.
        float left_req  = 0.15f * std_est;
        float right_req = 0.40f * std_est;
        
        if ((left_max - mid_val) > left_req && (right_max - mid_val) > right_req) {
            // WE FOUND THE PERFECT FOOT. 
            pending_foot2 = sample_count - 1u - APW2_W;
            apw2_refrac = APW2_REFRAC;
        }
    }
}

// =============================================================================
// Packet sender
// =============================================================================

void sendPacket(int32_t ecg1,int32_t bz1,int32_t ecg2,int32_t bz2,
                uint8_t flags, float vbus, float current, float power){
    uint8_t p[DATA_LEN]; memset(p,0,DATA_LEN);
    p[0] =(uint8_t)(ecg1      &0xFF);p[1] =(uint8_t)((ecg1>>8 )&0xFF);
    p[2] =(uint8_t)((ecg1>>16)&0xFF);p[3] =(uint8_t)((ecg1>>24)&0xFF);
    p[4] =(uint8_t)(bz1       &0xFF);p[5] =(uint8_t)((bz1 >>8 )&0xFF);
    p[6] =(uint8_t)((bz1 >>16)&0xFF);p[7] =(uint8_t)((bz1 >>24)&0xFF);
    p[8] =(uint8_t)(ecg2      &0xFF);p[9] =(uint8_t)((ecg2>>8 )&0xFF);
    p[10]=(uint8_t)((ecg2>>16)&0xFF);p[11]=(uint8_t)((ecg2>>24)&0xFF);
    p[12]=(uint8_t)(bz2       &0xFF);p[13]=(uint8_t)((bz2 >>8 )&0xFF);
    p[14]=(uint8_t)((bz2>>16) &0xFF);p[15]=(uint8_t)((bz2>>24) &0xFF);
    p[16]=flags;
    // INA219 Data (17 to 28) - Pack floats directly into bytes
    memcpy(&p[17], &vbus, 4);
    memcpy(&p[21], &current, 4);
    memcpy(&p[25], &power, 4);

    // Write to USB (if connected)
    if(Serial) {
        Serial.write(PKT_HDR,5); Serial.write(p,DATA_LEN); Serial.write(PKT_FTR,2);
    }

    Serial1.write(PKT_HDR, 5);
    Serial1.write(p, DATA_LEN);
    Serial1.write(PKT_FTR, 2);
}

// =============================================================================
// setup()
// =============================================================================

void setup(){
    Serial.begin(230400);
    Serial1.begin(57600);
    Wire.begin();
    
    pinMode(CS1_PIN,OUTPUT); digitalWrite(CS1_PIN,HIGH);
    pinMode(CS2_PIN,OUTPUT); digitalWrite(CS2_PIN,HIGH);
    delay(300);
    uint32_t t0=millis();
    while(!Serial&&(millis()-t0<3000)){}

    if (!ina219.begin()) {
        Serial.println(F("WARNING: INA219 not detected! Continuing anyway..."));
    } else {
        Serial.println(F("INA219 Initialized."));
    }

    Serial.println(F("\n=== Dual MAX30001 | STM32F411 | DSP v7.1 | 230400 ==="));

    Serial.println(F("\n=== Dual MAX30001 | STM32F411 | DSP v7.1 | 230400 ==="));
    Serial.println(F("APW1: ECG-triggered cubic-poly (first 50% of beat window)"));
    Serial.println(F("APW2: Self-triggered Asymmetric Morphological V-Shape"));

    SPI.begin(); delay(100);

    chip1_ok=initChip(chip1,CS1_PIN,CS2_PIN,"Chip1");
    deselectBoth(); delay(30);
    if(chip1_ok){
        digitalWrite(CS2_PIN,HIGH);
        Serial.print(F("Chip1 startECGBioZ... "));
        chip1_ok=(chip1.startECGBioZ(SAMPLE_RATE)==MAX30001_SUCCESS);
        Serial.println(chip1_ok?F("OK"):F("FAIL"));
        deselectBoth(); delay(30);
    }
    if(chip1_ok){
        uint32_t bz=readReg(CS1_PIN,REG_CNFG_BIOZ);
        bz&=~0x03C000UL; bz|=0x028000UL;
        writeReg(CS1_PIN,REG_CNFG_BIOZ,bz);
        deselectBoth(); delay(10);
        verifyBioZ(CS1_PIN,"Chip1");
        deselectBoth(); delay(30);
    }

    chip2_ok=initChip(chip2,CS2_PIN,CS1_PIN,"Chip2");
    deselectBoth(); delay(30);
    if(chip2_ok){
        digitalWrite(CS1_PIN,HIGH);
        Serial.print(F("Chip2 startECGBioZ... "));
        chip2_ok=(chip2.startECGBioZ(SAMPLE_RATE)==MAX30001_SUCCESS);
        Serial.println(chip2_ok?F("OK"):F("FAIL"));
        deselectBoth(); delay(30);
    }
    if(chip2_ok){
        uint32_t bz=readReg(CS2_PIN,REG_CNFG_BIOZ);
        bz&=~0x03C000UL; bz|=0x028000UL;
        writeReg(CS2_PIN,REG_CNFG_BIOZ,bz);
        deselectBoth(); delay(10);
        verifyBioZ(CS2_PIN,"Chip2");
        deselectBoth(); delay(30);
    }

    if(chip1_ok){writeReg(CS1_PIN,REG_SYNCH,0x000000UL);deselectBoth();delay(5);}
    if(chip2_ok){writeReg(CS2_PIN,REG_SYNCH,0x000000UL);deselectBoth();}

    if(!chip1_ok&&!chip2_ok) Serial.println(F("WARNING: both chips FAILED"));
    else Serial.println(F("Streaming. Open dual_ptt_onboard.py"));

    memset(ecg1_ring,0,sizeof(ecg1_ring));
    memset(bz1_ring, 0,sizeof(bz1_ring));
    memset(bz2_ring, 0,sizeof(bz2_ring));
    pending_foot1=NO_PENDING;
    pending_foot2=NO_PENDING;
    apw1_prev_rhead=NO_PENDING;
    lastSample=lastBanner=millis();
}

// =============================================================================
// loop()
// =============================================================================

void loop(){
    unsigned long now=millis();

    // INA219 Update (Runs every 500ms) 
    if (now - lastInaRead >= 500) {
        lastInaRead = now;
        last_vbus = ina219.getBusVoltage_V();
        last_current = ina219.getCurrent_mA();
        last_power = ina219.getPower_mW();
        // Load voltage is Vbus + (Shunt/1000). We can calculate this in Python  
    }

    // Waveform update
    if(now-lastSample<SAMPLE_PERIOD_MS) return;
    lastSample=now;

    // if(now-lastBanner>=5000UL){
    //     lastBanner=now;
    //     Serial.print(F("# pkt=")); Serial.print(pktCount);
    //     Serial.print(F(" c1=")); Serial.print(chip1_ok?F("OK"):F("FAIL"));
    //     Serial.print(F(" c2=")); Serial.print(chip2_ok?F("OK"):F("FAIL"));
    //     Serial.print(F(" BZ1=")); Serial.print(bz1_ring[(ring_head-1u)&RING_MASK]);
    //     Serial.print(F(" BZ2=")); Serial.println(bz2_ring[(ring_head-1u)&RING_MASK]);
    //     Serial.print(F(" pf1=")); Serial.print(pending_foot1);
    //     Serial.print(F(" pf2=")); Serial.println(pending_foot2);
    // }

    // ── Acquire ───────────────────────────────────────────────────────────────
    int32_t ecg1_v=0,ecg2_v=0;
    int32_t bz1_v=bz1_ring[(ring_head-1u)&RING_MASK];
    int32_t bz2_v=bz2_ring[(ring_head-1u)&RING_MASK];

    if(chip1_ok){
        digitalWrite(CS2_PIN,HIGH);
        max30001_ecg_sample_t es;
        if(chip1.getECGSample(&es)==MAX30001_SUCCESS&&es.sample_valid)
            ecg1_v=es.ecg_sample;
        if(!skip1){
            max30001_bioz_sample_t bs;
            if(chip1.getBioZSample(&bs)==MAX30001_SUCCESS&&bs.sample_valid)
                bz1_v=bs.bioz_sample;
        }
        skip1=!skip1; deselectBoth();
    }

    if(chip2_ok){
        digitalWrite(CS1_PIN,HIGH);
        max30001_ecg_sample_t es;
        if(chip2.getECGSample(&es)==MAX30001_SUCCESS&&es.sample_valid)
            ecg2_v=es.ecg_sample;
        if(!skip2){
            max30001_bioz_sample_t bs;
            if(chip2.getBioZSample(&bs)==MAX30001_SUCCESS&&bs.sample_valid)
                bz2_v=bs.bioz_sample;
        }
        skip2=!skip2; deselectBoth();
    }

    // ── Push to ring ──────────────────────────────────────────────────────────
    ecg1_ring[ring_head]=ecg1_v;
    bz1_ring [ring_head]=bz1_v;
    bz2_ring [ring_head]=bz2_v;
    ring_head=(ring_head+1u)&RING_MASK;
    sample_count++;

    // ── Clear flags ───────────────────────────────────────────────────────────
    flag_rpeak=false; flag_foot1=false; flag_foot2=false;

    // =========================================================================
    // APW1 PIPELINE — ECG R-peak → cubic-poly foot on BZ1
    // =========================================================================
    if(pt_push(ecg1_v)){
        flag_rpeak=true;
        uint32_t curr=ring_head;
        if(apw1_prev_rhead!=NO_PENDING){
            uint32_t bl=(curr-apw1_prev_rhead)&RING_MASK;
            if(bl>=(uint32_t)APW1_WIN_MIN && bl<=(uint32_t)APW1_WIN_MAX){
                uint8_t nw=(apw1_jwr+1u)%MAX_APW1_JOBS;
                if(nw!=apw1_jrd){
                    apw1_jobs[apw1_jwr]={apw1_prev_rhead,bl};
                    apw1_jwr=nw;
                }
            }
        }
        apw1_prev_rhead=curr;
    }
    apw1_run_job(); 

    // =========================================================================
    // APW2 PIPELINE — Self-Triggered Asymmetric Morphological V-Shape
    // =========================================================================
    apw2_push(bz2_v); 

    // =========================================================================
    // Fire pending flags
    // =========================================================================
    if(pending_foot1!=NO_PENDING && sample_count>=pending_foot1){
        flag_foot1=true;
        pending_foot1=NO_PENDING;
    }
    if(pending_foot2!=NO_PENDING && sample_count>=pending_foot2){
        flag_foot2=true;
        pending_foot2=NO_PENDING;
    }

    // ── Transmit ──────────────────────────────────────────────────────────────
    uint8_t flags=0;
    if(flag_rpeak) flags|=0x01u;
    if(flag_foot1) flags|=0x02u;
    if(flag_foot2) flags|=0x04u;
    sendPacket(ecg1_v,bz1_v,ecg2_v,bz2_v,flags,last_vbus,last_current,last_power);
    pktCount++;
}
