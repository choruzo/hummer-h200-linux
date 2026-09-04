/* Logging proxy for hidapi.dll (32-bit, cdecl).
   Forwards every call to hidapi_real.dll and logs bytes to C:\hidlog.txt */
#include <windows.h>
#include <stdio.h>
#include <stddef.h>

static HMODULE g_real = NULL;
static CRITICAL_SECTION g_cs;
static int g_inited = 0;

static void logline(const char *fmt, ...);

static void ensure_init(void)
{
    if (g_inited) return;
    InitializeCriticalSection(&g_cs);
    g_inited = 1;
    g_real = LoadLibraryA("C:\\Program Files (x86)\\Hummer_Digital\\hidapi_real.dll");
    logline("=== proxy loaded, real=%p ===", (void*)g_real);
}

static void logline(const char *fmt, ...)
{
    FILE *f = fopen("C:\\hidlog.txt", "a");
    if (!f) return;
    SYSTEMTIME st; GetLocalTime(&st);
    fprintf(f, "[%02d:%02d:%02d.%03d] ", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
    va_list ap; va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

static void loghex(const char *tag, const void *dev, const unsigned char *b, int n)
{
    FILE *f = fopen("C:\\hidlog.txt", "a");
    if (!f) return;
    SYSTEMTIME st; GetLocalTime(&st);
    fprintf(f, "[%02d:%02d:%02d.%03d] %s dev=%p len=%d :", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, tag, dev, n);
    int i;
    for (i = 0; i < n; i++) fprintf(f, " %02X", b[i]);
    fputc('\n', f);
    fclose(f);
}

#define GETFN(name, type) \
    static type p_##name = NULL; \
    if (!p_##name) { ensure_init(); p_##name = (type)GetProcAddress(g_real, #name); \
      if (!p_##name) logline("!! GetProcAddress failed: %s", #name); }

typedef int  (__cdecl *fn_init)(void);
typedef int  (__cdecl *fn_exit)(void);
typedef void*(__cdecl *fn_enum)(unsigned short, unsigned short);
typedef void (__cdecl *fn_freeenum)(void*);
typedef void*(__cdecl *fn_openpath)(const char*);
typedef void*(__cdecl *fn_open)(unsigned short, unsigned short, const wchar_t*);
typedef int  (__cdecl *fn_write)(void*, const unsigned char*, size_t);
typedef int  (__cdecl *fn_read)(void*, unsigned char*, size_t);
typedef int  (__cdecl *fn_readto)(void*, unsigned char*, size_t, int);
typedef int  (__cdecl *fn_nonblock)(void*, int);
typedef void (__cdecl *fn_close)(void*);
typedef const wchar_t* (__cdecl *fn_error)(void*);
typedef int  (__cdecl *fn_feature)(void*, unsigned char*, size_t);
typedef int  (__cdecl *fn_str)(void*, wchar_t*, size_t);

__declspec(dllexport) int __cdecl hid_init(void)
{ GETFN(hid_init, fn_init); int r = p_hid_init ? p_hid_init() : -1; logline("hid_init -> %d", r); return r; }

__declspec(dllexport) int __cdecl hid_exit(void)
{ GETFN(hid_exit, fn_exit); int r = p_hid_exit ? p_hid_exit() : -1; logline("hid_exit -> %d", r); return r; }

__declspec(dllexport) void* __cdecl hid_enumerate(unsigned short v, unsigned short p)
{
    GETFN(hid_enumerate, fn_enum);
    void *r = p_hid_enumerate ? p_hid_enumerate(v, p) : NULL;
    logline("hid_enumerate(%04X,%04X) -> %p", v, p, r);
    /* walk the list: layout path,vid,pid,serial,rel,mfg,prod,up,usage,iface,next(0x20) */
    unsigned char *cur = (unsigned char*)r; int n = 0;
    while (cur && n < 64) {
        char *path = *(char**)(cur + 0);
        unsigned short vid = *(unsigned short*)(cur + 4);
        unsigned short pid = *(unsigned short*)(cur + 6);
        wchar_t *ser = *(wchar_t**)(cur + 8);
        logline("   [%d] %04X:%04X serial=%s%ls%s path=%s", n, vid, pid,
                ser ? "" : "(NULL", ser ? ser : L"", ser ? "" : ")", path ? path : "(null)");
        cur = *(unsigned char**)(cur + 0x20);
        n++;
    }
    return r;
}

__declspec(dllexport) void __cdecl hid_free_enumeration(void *d)
{ GETFN(hid_free_enumeration, fn_freeenum); if (p_hid_free_enumeration) p_hid_free_enumeration(d); }

__declspec(dllexport) void* __cdecl hid_open_path(const char *path)
{ GETFN(hid_open_path, fn_openpath); void *r = p_hid_open_path ? p_hid_open_path(path) : NULL;
  logline("hid_open_path(%s) -> %p", path ? path : "(null)", r); return r; }

__declspec(dllexport) void* __cdecl hid_open(unsigned short v, unsigned short p, const wchar_t *s)
{ GETFN(hid_open, fn_open); void *r = p_hid_open ? p_hid_open(v, p, s) : NULL;
  logline("hid_open(%04X,%04X) -> %p", v, p, r); return r; }

__declspec(dllexport) int __cdecl hid_write(void *dev, const unsigned char *data, size_t len)
{
    GETFN(hid_write, fn_write);
    loghex("WRITE", dev, data, (int)len);
    int r = p_hid_write ? p_hid_write(dev, data, len) : -1;
    logline("   hid_write -> %d", r);
    return r;
}

__declspec(dllexport) int __cdecl hid_read(void *dev, unsigned char *data, size_t len)
{
    GETFN(hid_read, fn_read);
    int r = p_hid_read ? p_hid_read(dev, data, len) : -1;
    if (r > 0) loghex("READ ", dev, data, r);
    else logline("READ  dev=%p -> %d", dev, r);
    return r;
}

__declspec(dllexport) int __cdecl hid_read_timeout(void *dev, unsigned char *data, size_t len, int ms)
{
    GETFN(hid_read_timeout, fn_readto);
    int r = p_hid_read_timeout ? p_hid_read_timeout(dev, data, len, ms) : -1;
    if (r > 0) loghex("READt", dev, data, r);
    else logline("READt dev=%p -> %d", dev, r);
    return r;
}

__declspec(dllexport) int __cdecl hid_set_nonblocking(void *dev, int nb)
{ GETFN(hid_set_nonblocking, fn_nonblock); int r = p_hid_set_nonblocking ? p_hid_set_nonblocking(dev, nb) : -1;
  logline("hid_set_nonblocking(%p,%d) -> %d", dev, nb, r); return r; }

__declspec(dllexport) void __cdecl hid_close(void *dev)
{ GETFN(hid_close, fn_close); logline("hid_close(%p)", dev); if (p_hid_close) p_hid_close(dev); }

__declspec(dllexport) const wchar_t* __cdecl hid_error(void *dev)
{ GETFN(hid_error, fn_error); const wchar_t *r = p_hid_error ? p_hid_error(dev) : NULL;
  logline("hid_error(%p) -> %ls", dev, r ? r : L"(null)"); return r; }

__declspec(dllexport) int __cdecl hid_send_feature_report(void *dev, const unsigned char *d, size_t l)
{ GETFN(hid_send_feature_report, fn_write); loghex("SFEAT", dev, d, (int)l);
  return p_hid_send_feature_report ? p_hid_send_feature_report(dev, d, l) : -1; }

__declspec(dllexport) int __cdecl hid_get_feature_report(void *dev, unsigned char *d, size_t l)
{ GETFN(hid_get_feature_report, fn_feature); int r = p_hid_get_feature_report ? p_hid_get_feature_report(dev, d, l) : -1;
  if (r > 0) loghex("GFEAT", dev, d, r); return r; }

__declspec(dllexport) int __cdecl hid_get_manufacturer_string(void *dev, wchar_t *s, size_t l)
{ GETFN(hid_get_manufacturer_string, fn_str); return p_hid_get_manufacturer_string ? p_hid_get_manufacturer_string(dev, s, l) : -1; }

__declspec(dllexport) int __cdecl hid_get_product_string(void *dev, wchar_t *s, size_t l)
{ GETFN(hid_get_product_string, fn_str); return p_hid_get_product_string ? p_hid_get_product_string(dev, s, l) : -1; }

__declspec(dllexport) int __cdecl hid_get_serial_number_string(void *dev, wchar_t *s, size_t l)
{ GETFN(hid_get_serial_number_string, fn_str); return p_hid_get_serial_number_string ? p_hid_get_serial_number_string(dev, s, l) : -1; }

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID r)
{ if (reason == DLL_PROCESS_ATTACH) { ensure_init(); } return TRUE; }
