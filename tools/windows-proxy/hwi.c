/* Fake HWiNFO32.dll for the H-200 protocol capture.
   API recovered from Hummer_Digital.exe (HardwareInfoReader::InitHWi32Dll /
   ReadHWInfoByHWi32Dll), all __cdecl, exported by ordinal only:
     @127 init(int)                       -> 0 on success
     @466 unknown                         -> 0
     @781 device_count(void)              -> N
     @617 select_device(int idx)
     @168 device_name(int idx, char *buf, int len)
     @570 sensor(int type, int dev, int idx, char buf[0x1d0]) -> 0 = no more
          buf+0x000 dword  valid flag
          buf+0x008 double value
          buf+0x010 char[] unit
          buf+0x148 char[] label
   Values are read from C:\hwi_fake.txt: "<cpu_temp> <gpu_temp> <fan_rpm>". */
#include <windows.h>
#include <stdio.h>

static void logf_(const char *fmt, ...)
{
    FILE *f = fopen("C:\\hwilog.txt", "a");
    if (!f) return;
    va_list ap; va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
    fputc('\n', f); fclose(f);
}

static void values(double *cpu, double *gpu, double *fan)
{
    *cpu = 55.0; *gpu = 44.0; *fan = 1234.0;
    FILE *f = fopen("C:\\hwi_fake.txt", "r");
    if (f) { fscanf(f, "%lf %lf %lf", cpu, gpu, fan); fclose(f); }
}

__declspec(dllexport) int __cdecl hwi_init(int a)
{ logf_("init(%d)", a); return 0; }

__declspec(dllexport) int __cdecl hwi_unk466(int a)
{ logf_("unk466(%d)", a); return 0; }

__declspec(dllexport) int __cdecl hwi_count(void)
{ logf_("count()"); return 1; }

__declspec(dllexport) int __cdecl hwi_select(int idx)
{ logf_("select(%d)", idx); return 0; }

__declspec(dllexport) int __cdecl hwi_name(int idx, char *buf, int len)
{
    logf_("name(%d,%p,%d)", idx, buf, len);
    if (buf && len > 0) { strncpy(buf, "System", len - 1); buf[len - 1] = 0; }
    return 0;
}

static int fill(char *b, double v, const char *unit, const char *label)
{
    memset(b, 0, 0x1d0);
    *(int *)(b + 0x00) = 1;
    *(double *)(b + 0x08) = v;
    strcpy(b + 0x10, unit);
    strcpy(b + 0x148, label);
    return 1;
}

__declspec(dllexport) int __cdecl hwi_sensor(int type, int dev, int idx, char *buf)
{
    double cpu, gpu, fan;
    values(&cpu, &gpu, &fan);
    logf_("sensor(type=%d dev=%d idx=%d) cpu=%.1f gpu=%.1f fan=%.1f", type, dev, idx, cpu, gpu, fan);
    if (!buf || dev != 0) return 0;
    if (type == 1) {                       /* temperatures */
        if (idx == 0) return fill(buf, cpu, "", "CPU Package");
        if (idx == 1) return fill(buf, gpu, "", "GPU Temperature");
        return 0;
    }
    if (type == 3) {                       /* fans */
        if (idx == 0) return fill(buf, fan, "RPM", "CPU Fan RPM");
        return 0;
    }
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD r, LPVOID x) { return TRUE; }
