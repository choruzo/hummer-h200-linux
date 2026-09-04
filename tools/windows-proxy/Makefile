# Cross-build the two Windows DLL shims used to instrument Hummer_Digital.exe.
# Needs: apt install gcc-mingw-w64-i686-win32   (the app and its DLLs are 32-bit)
#
#   hidapi_proxy.dll   -> install as  hidapi.dll   (rename the original to hidapi_real.dll)
#                         logs every hid_* call and report byte to C:\hidlog.txt
#   HWiNFO32_fake.dll  -> install as  HWiNFO32.dll (keep the original as HWiNFO32_orig.dll)
#                         feeds the app synthetic CPU/GPU temperature and fan RPM,
#                         read from C:\hwi_fake.txt ("<cpu> <gpu> <rpm>")

CC := i686-w64-mingw32-gcc
CFLAGS := -O1 -static-libgcc

all: hidapi_proxy.dll HWiNFO32_fake.dll

hidapi_proxy.dll: proxy.c hidapi.def
	$(CC) $(CFLAGS) -shared -o $@ proxy.c hidapi.def

HWiNFO32_fake.dll: hwi.c hwi.def
	$(CC) $(CFLAGS) -shared -o $@ hwi.c hwi.def

clean:
	rm -f hidapi_proxy.dll HWiNFO32_fake.dll

.PHONY: all clean
