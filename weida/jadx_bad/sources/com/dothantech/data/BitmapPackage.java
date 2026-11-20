package com.dothantech.data;

import android.graphics.Bitmap;
import android.os.Bundle;
import android.os.Handler;
import androidx.media3.common.PlaybackException;
import com.dothantech.bluetooth.BluetoothUtils;
import com.dothantech.common.DzArrays;
import com.dothantech.common.DzBitmap;
import com.dothantech.common.DzConfig;
import com.dothantech.common.d0;
import com.dothantech.common.i0;
import com.dothantech.common.k;
import com.dothantech.data.d;
import com.dothantech.printer.b;
import com.huawei.hms.network.embedded.c1;
import com.huawei.hms.network.okhttp.PublicSuffixDatabase;

/* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
/* loaded from: classes.dex */
public class BitmapPackage {

    /* renamed from: d0, reason: collision with root package name */
    public static final i0 f3144d0 = i0.g("DzPrinter.BitmapPackage");

    /* renamed from: e0, reason: collision with root package name */
    public static boolean f3145e0 = DzConfig.b(j1.a.DzPrinter_support_super_bitmap, true);
    protected int A;
    protected int B;
    protected int C;
    protected boolean D;
    protected boolean E;
    protected int F;
    protected int G;
    protected int H;
    protected int I;
    protected f J;
    protected g K;
    protected g L;
    protected int M;
    protected int N;
    protected int O;
    protected int P;
    protected int Q;
    protected int R;
    protected int S;
    protected int T;
    protected int U;
    protected int V;
    protected int W;
    protected int X;
    protected int Y;
    protected int Z;

    /* renamed from: a, reason: collision with root package name */
    public final boolean f3146a;

    /* renamed from: a0, reason: collision with root package name */
    protected int f3147a0;

    /* renamed from: b, reason: collision with root package name */
    public boolean f3148b;

    /* renamed from: b0, reason: collision with root package name */
    protected int f3149b0;

    /* renamed from: c, reason: collision with root package name */
    protected b f3150c;

    /* renamed from: c0, reason: collision with root package name */
    protected int f3151c0;

    /* renamed from: d, reason: collision with root package name */
    protected d.a f3152d;

    /* renamed from: e, reason: collision with root package name */
    protected final BluetoothUtils.c f3153e;

    /* renamed from: f, reason: collision with root package name */
    protected final b.c f3154f;

    /* renamed from: g, reason: collision with root package name */
    protected final int f3155g;

    /* renamed from: h, reason: collision with root package name */
    protected final short f3156h;

    /* renamed from: i, reason: collision with root package name */
    protected final int f3157i;

    /* renamed from: j, reason: collision with root package name */
    protected final int f3158j;

    /* renamed from: k, reason: collision with root package name */
    protected int f3159k;

    /* renamed from: l, reason: collision with root package name */
    protected int f3160l;

    /* renamed from: m, reason: collision with root package name */
    protected DzBitmap.Direction f3161m;

    /* renamed from: n, reason: collision with root package name */
    protected int f3162n;

    /* renamed from: o, reason: collision with root package name */
    protected int f3163o;

    /* renamed from: p, reason: collision with root package name */
    protected int f3164p;

    /* renamed from: q, reason: collision with root package name */
    protected LineAction f3165q;

    /* renamed from: r, reason: collision with root package name */
    protected int f3166r;

    /* renamed from: s, reason: collision with root package name */
    protected int f3167s;

    /* renamed from: t, reason: collision with root package name */
    protected byte[] f3168t;

    /* renamed from: u, reason: collision with root package name */
    protected int f3169u;

    /* renamed from: v, reason: collision with root package name */
    protected byte[] f3170v;

    /* renamed from: w, reason: collision with root package name */
    protected int[] f3171w;

    /* renamed from: x, reason: collision with root package name */
    protected int f3172x;

    /* renamed from: y, reason: collision with root package name */
    protected int f3173y;

    /* renamed from: z, reason: collision with root package name */
    protected int f3174z;

    /* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
    protected enum LineAction {
        None,
        Line,
        Print
    }

    /* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
    static /* synthetic */ class a {

        /* renamed from: a, reason: collision with root package name */
        static final /* synthetic */ int[] f3179a;

        static {
            int[] iArr = new int[LineAction.values().length];
            f3179a = iArr;
            try {
                iArr[LineAction.Line.ordinal()] = 1;
            } catch (NoSuchFieldError unused) {
            }
            try {
                f3179a[LineAction.Print.ordinal()] = 2;
            } catch (NoSuchFieldError unused2) {
            }
        }
    }

    /* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
    protected class b implements com.dothantech.data.c {

        /* renamed from: a, reason: collision with root package name */
        final int f3180a = PlaybackException.CUSTOM_ERROR_CODE_BASE;

        /* renamed from: b, reason: collision with root package name */
        Bitmap f3181b;

        /* renamed from: c, reason: collision with root package name */
        boolean f3182c;

        /* renamed from: d, reason: collision with root package name */
        int f3183d;

        /* renamed from: e, reason: collision with root package name */
        int f3184e;

        /* renamed from: f, reason: collision with root package name */
        int f3185f;

        /* renamed from: g, reason: collision with root package name */
        int f3186g;

        /* renamed from: h, reason: collision with root package name */
        int f3187h;

        /* renamed from: i, reason: collision with root package name */
        int f3188i;

        /* renamed from: j, reason: collision with root package name */
        d.a f3189j;

        /* renamed from: k, reason: collision with root package name */
        d.b f3190k;

        /* renamed from: l, reason: collision with root package name */
        int f3191l;

        /* renamed from: m, reason: collision with root package name */
        int f3192m;

        /* renamed from: n, reason: collision with root package name */
        int f3193n;

        /* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
        class a implements Runnable {
            a() {
            }

            @Override // java.lang.Runnable
            public void run() {
                b.this.f(false);
            }
        }

        b(Bitmap bitmap, boolean z8, int i8, int i9, int i10, int i11, int i12, int i13) {
            this.f3181b = bitmap;
            this.f3182c = z8;
            this.f3183d = i8;
            this.f3184e = i9;
            this.f3185f = i10;
            this.f3186g = i11;
            this.f3187h = i12;
            this.f3188i = i13;
            d.a aVar = BitmapPackage.this.f3152d;
            this.f3189j = aVar;
            this.f3190k = aVar.c();
        }

        @Override // com.dothantech.data.c
        public boolean a() {
            return this.f3190k == this.f3189j.c();
        }

        @Override // com.dothantech.data.c
        public com.dothantech.data.d b(int i8) {
            if ((this.f3190k == null && (!f(false) || this.f3190k == null)) || this.f3190k.c() > i8) {
                return null;
            }
            if (this.f3190k.m() == null || this.f3190k.c() + this.f3190k.m().c() > i8) {
                d.b bVar = this.f3190k;
                this.f3190k = bVar.m();
                return bVar;
            }
            com.dothantech.data.d dVar = new com.dothantech.data.d(i8);
            while (true) {
                d.b bVar2 = this.f3190k;
                if (bVar2 == null || !dVar.l(bVar2.a(), this.f3190k.c())) {
                    break;
                }
                this.f3190k = this.f3190k.m();
            }
            return dVar;
        }

        @Override // com.dothantech.data.c
        public boolean c() {
            d.b c9 = this.f3189j.c();
            this.f3190k = c9;
            return c9 != null;
        }

        @Override // com.dothantech.data.c
        public int d() {
            if (this.f3190k != null || (f(false) && this.f3190k != null)) {
                return this.f3190k.c();
            }
            return 0;
        }

        boolean e() {
            return BitmapPackage.this.f3165q == LineAction.None;
        }

        boolean f(boolean z8) {
            int i8;
            if (e()) {
                return false;
            }
            i0 i0Var = BitmapPackage.f3144d0;
            if (i0Var.c()) {
                i0Var.a(String.format("BitmapBandPackage.printBand() start. currentRow = %d", Integer.valueOf(this.f3184e)));
            }
            BitmapPackage bitmapPackage = BitmapPackage.this;
            bitmapPackage.f3172x = 0;
            bitmapPackage.f3173y = 0;
            bitmapPackage.f3174z = 0;
            bitmapPackage.A = 0;
            bitmapPackage.B = 0;
            bitmapPackage.f3170v = null;
            bitmapPackage.f3152d = new d.a();
            int i9 = (z8 ? PlaybackException.CUSTOM_ERROR_CODE_BASE / this.f3185f : PlaybackException.CUSTOM_ERROR_CODE_BASE / (this.f3185f * 3)) + 1;
            int i10 = this.f3184e;
            int i11 = i10 + i9;
            int i12 = this.f3186g;
            if (i11 > i12) {
                i9 = i12 - i10;
            }
            int i13 = i9;
            boolean z9 = i10 + i13 >= i12;
            int i14 = this.f3185f;
            int[] iArr = new int[i14 * i13];
            this.f3181b.getPixels(iArr, 0, i14, 0, i10, i14, i13);
            if (i0Var.c()) {
                i0Var.a(String.format("BitmapBandPackage.printBand() after printBitmap.getPixels()", new Object[0]));
            }
            for (int i15 = 0; i15 < i13; i15++) {
                byte[] bArr = new byte[BitmapPackage.this.f3159k];
                int i16 = (this.f3185f * i15) + this.f3183d;
                for (int i17 = 0; i17 < this.f3188i; i17++) {
                    int A = DzBitmap.A(iArr[i16 + i17]);
                    BitmapPackage bitmapPackage2 = BitmapPackage.this;
                    if ((A < bitmapPackage2.f3164p) != bitmapPackage2.D) {
                        int i18 = this.f3187h + i17;
                        int i19 = i18 >>> 3;
                        bArr[i19] = (byte) ((128 >>> (i18 & 7)) | bArr[i19]);
                    }
                }
                BitmapPackage.this.g(bArr);
            }
            this.f3184e += i13;
            d.b bVar = new d.b(8);
            BitmapPackage bitmapPackage3 = BitmapPackage.this;
            int i20 = bitmapPackage3.f3174z;
            int i21 = bitmapPackage3.A;
            bVar.j((byte) 37, new byte[]{(byte) ((i20 >>> 8) | 192), (byte) (i20 & 255), (byte) ((i21 >>> 8) | 192), (byte) (i21 & 255)}, 4);
            if (this.f3189j.b(bVar) && this.f3190k == null) {
                this.f3190k = bVar;
            }
            int i22 = this.f3191l;
            BitmapPackage bitmapPackage4 = BitmapPackage.this;
            int i23 = bitmapPackage4.f3174z;
            if (i22 < i23) {
                this.f3191l = i23;
            }
            int i24 = this.f3192m;
            int i25 = bitmapPackage4.A;
            if (i24 < i25) {
                this.f3192m = i25;
            }
            int i26 = this.f3193n;
            if (i26 <= 0 || ((i8 = bitmapPackage4.B) > 0 && i26 > i8)) {
                this.f3193n = bitmapPackage4.B;
            }
            i0 i0Var2 = BitmapPackage.f3144d0;
            if (i0Var2.c()) {
                i0Var2.a(String.format("BitmapBandPackage.printBand() end. bandRows = %d", Integer.valueOf(i13)));
                i0Var2.a(String.format("BitmapBandPackage.printBand()  BitmapPackage.this.mBuffer.totalLength() = %d", Integer.valueOf(BitmapPackage.this.f3152d.k())));
                i0Var2.a(String.format("BitmapBandPackage.printBand()    BitmapPackage.this.mMaxLEDots = %d", Integer.valueOf(BitmapPackage.this.A)));
                i0Var2.a(String.format("BitmapBandPackage.printBand()                  this.mMaxLEDots = %d", Integer.valueOf(this.f3192m)));
            }
            if (z9) {
                BitmapPackage bitmapPackage5 = BitmapPackage.this;
                bitmapPackage5.f3174z = this.f3191l;
                bitmapPackage5.A = this.f3192m;
                bitmapPackage5.B = this.f3193n;
                bitmapPackage5.a();
                if (this.f3182c) {
                    this.f3181b.recycle();
                }
                this.f3181b = null;
            } else {
                int i27 = a.f3179a[BitmapPackage.this.f3165q.ordinal()];
                if (i27 == 1) {
                    BitmapPackage bitmapPackage6 = BitmapPackage.this;
                    bitmapPackage6.i(bitmapPackage6.f3166r);
                } else if (i27 == 2) {
                    BitmapPackage.this.q();
                }
                BitmapPackage bitmapPackage7 = BitmapPackage.this;
                bitmapPackage7.f3165q = LineAction.Line;
                bitmapPackage7.f3166r = 0;
                new Handler().postDelayed(new a(), 10L);
            }
            if (this.f3190k == null) {
                this.f3190k = BitmapPackage.this.f3152d.c();
            }
            this.f3189j.a(BitmapPackage.this.f3152d);
            if (i0Var2.c() && z9) {
                i0Var2.a(String.format("BitmapBandPackage.printBand() finished. this.mBuffer.totalLength() = %d", Integer.valueOf(this.f3189j.k())));
            }
            return true;
        }

        @Override // com.dothantech.data.c
        public boolean isEmpty() {
            return this.f3190k == null && e();
        }
    }

    /* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
    protected static class c extends h {

        /* renamed from: d, reason: collision with root package name */
        protected static final short[] f3196d = {1, 2, 3, 4, 9, 14, 29, 88};

        protected c() {
        }

        @Override // com.dothantech.data.BitmapPackage.h
        public int a() {
            return 4;
        }

        public boolean e(boolean z8, int i8) {
            int i9 = (this.f3208b * 4) / 8;
            int length = f3196d.length - 1;
            while (i8 > 0) {
                short s8 = f3196d[length];
                if (i8 >= s8) {
                    i8 -= s8;
                    int i10 = (z8 ? 8 : 0) | length;
                    int i11 = this.f3208b + 1;
                    this.f3208b = i11;
                    if (i11 * 4 > this.f3209c * 8) {
                        return false;
                    }
                    int i12 = i11 & 1;
                    if (i12 == 0) {
                        byte[] bArr = this.f3207a;
                        bArr[i9] = (byte) (i10 | bArr[i9]);
                        i9++;
                    } else if (i12 == 1) {
                        byte[] bArr2 = this.f3207a;
                        bArr2[i9] = (byte) ((i10 << 4) | bArr2[i9]);
                    }
                } else {
                    length = i8 <= 4 ? i8 - 1 : length - 1;
                }
            }
            return true;
        }
    }

    /* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
    protected static class d extends h {

        /* renamed from: d, reason: collision with root package name */
        protected static final short[] f3197d = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 24, 36, 48, 120};

        protected d() {
        }

        @Override // com.dothantech.data.BitmapPackage.h
        public int a() {
            return 5;
        }

        public boolean e(boolean z8, int i8) {
            int i9;
            int i10 = (this.f3208b * 5) / 8;
            int length = f3197d.length - 1;
            while (i8 > 0) {
                short s8 = f3197d[length];
                if (i8 >= s8) {
                    i8 -= s8;
                    int i11 = (z8 ? 16 : 0) | length;
                    int i12 = this.f3208b + 1;
                    this.f3208b = i12;
                    if (i12 * 5 > this.f3209c * 8) {
                        return false;
                    }
                    switch (i12 & 7) {
                        case 0:
                            byte[] bArr = this.f3207a;
                            i9 = i10 + 1;
                            bArr[i10] = (byte) (i11 | bArr[i10]);
                            break;
                        case 1:
                            byte[] bArr2 = this.f3207a;
                            bArr2[i10] = (byte) ((i11 << 3) | bArr2[i10]);
                            continue;
                        case 2:
                            byte[] bArr3 = this.f3207a;
                            i9 = i10 + 1;
                            bArr3[i10] = (byte) (bArr3[i10] | (i11 >>> 2));
                            bArr3[i9] = (byte) (bArr3[i9] | ((i11 & 3) << 6));
                            break;
                        case 3:
                            byte[] bArr4 = this.f3207a;
                            bArr4[i10] = (byte) ((i11 << 1) | bArr4[i10]);
                            continue;
                        case 4:
                            byte[] bArr5 = this.f3207a;
                            i9 = i10 + 1;
                            bArr5[i10] = (byte) (bArr5[i10] | (i11 >>> 4));
                            bArr5[i9] = (byte) (bArr5[i9] | ((i11 & 15) << 4));
                            break;
                        case 5:
                            byte[] bArr6 = this.f3207a;
                            i9 = i10 + 1;
                            bArr6[i10] = (byte) (bArr6[i10] | (i11 >>> 1));
                            bArr6[i9] = (byte) (bArr6[i9] | ((i11 & 1) << 7));
                            break;
                        case 6:
                            byte[] bArr7 = this.f3207a;
                            bArr7[i10] = (byte) ((i11 << 2) | bArr7[i10]);
                            continue;
                        case 7:
                            byte[] bArr8 = this.f3207a;
                            i9 = i10 + 1;
                            bArr8[i10] = (byte) (bArr8[i10] | (i11 >>> 3));
                            bArr8[i9] = (byte) (bArr8[i9] | ((i11 & 7) << 5));
                            break;
                    }
                    i10 = i9;
                } else {
                    length = i8 <= 12 ? i8 - 1 : length - 1;
                }
            }
            return true;
        }
    }

    /* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
    protected static class e extends h {

        /* renamed from: d, reason: collision with root package name */
        protected static final short[] f3198d = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 41, 62, 83, 104, 125, 146, 167, 188, 209, 230, 461, 923};

        protected e() {
        }

        @Override // com.dothantech.data.BitmapPackage.h
        public int a() {
            return 6;
        }

        public boolean e(boolean z8, int i8) {
            int i9;
            int i10 = (this.f3208b * 6) / 8;
            int length = f3198d.length - 1;
            while (i8 > 0) {
                short s8 = f3198d[length];
                if (i8 >= s8) {
                    i8 -= s8;
                    int i11 = (z8 ? 32 : 0) | length;
                    int i12 = this.f3208b + 1;
                    this.f3208b = i12;
                    if (i12 * 6 > this.f3209c * 8) {
                        return false;
                    }
                    int i13 = i12 & 3;
                    if (i13 == 0) {
                        byte[] bArr = this.f3207a;
                        i9 = i10 + 1;
                        bArr[i10] = (byte) (i11 | bArr[i10]);
                    } else if (i13 == 1) {
                        byte[] bArr2 = this.f3207a;
                        bArr2[i10] = (byte) ((i11 << 2) | bArr2[i10]);
                    } else if (i13 == 2) {
                        byte[] bArr3 = this.f3207a;
                        i9 = i10 + 1;
                        bArr3[i10] = (byte) (bArr3[i10] | (i11 >>> 4));
                        bArr3[i9] = (byte) (bArr3[i9] | ((i11 & 15) << 4));
                    } else if (i13 == 3) {
                        byte[] bArr4 = this.f3207a;
                        i9 = i10 + 1;
                        bArr4[i10] = (byte) (bArr4[i10] | (i11 >>> 2));
                        bArr4[i9] = (byte) (bArr4[i9] | ((i11 & 3) << 6));
                    }
                    i10 = i9;
                } else {
                    length = i8 <= 20 ? i8 - 1 : length - 1;
                }
            }
            return true;
        }
    }

    /* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
    protected static class f {

        /* renamed from: a, reason: collision with root package name */
        public final byte[] f3199a;

        /* renamed from: b, reason: collision with root package name */
        public int f3200b;

        /* renamed from: c, reason: collision with root package name */
        protected int f3201c;

        public f(int i8) {
            this.f3199a = new byte[i8 + 2];
        }

        protected boolean a(byte b9, int i8) {
            while (i8 >= 63) {
                int i9 = this.f3200b;
                if (i9 + 2 > this.f3201c) {
                    return false;
                }
                byte[] bArr = this.f3199a;
                int i10 = i9 + 1;
                this.f3200b = i10;
                bArr[i9] = -1;
                this.f3200b = i9 + 2;
                bArr[i10] = b9;
                i8 -= 63;
            }
            if (i8 != 0) {
                if (i8 != 1) {
                    int i11 = this.f3200b;
                    if (i11 + 2 > this.f3201c) {
                        return false;
                    }
                    byte[] bArr2 = this.f3199a;
                    int i12 = i11 + 1;
                    this.f3200b = i12;
                    bArr2[i11] = (byte) (i8 | 192);
                    this.f3200b = i11 + 2;
                    bArr2[i12] = b9;
                } else {
                    if ((b9 & 255) > 192) {
                        int i13 = this.f3200b;
                        if (i13 + 2 > this.f3201c) {
                            return false;
                        }
                        byte[] bArr3 = this.f3199a;
                        this.f3200b = i13 + 1;
                        bArr3[i13] = -63;
                    } else if (this.f3200b + 1 > this.f3201c) {
                        return false;
                    }
                    byte[] bArr4 = this.f3199a;
                    int i14 = this.f3200b;
                    this.f3200b = i14 + 1;
                    bArr4[i14] = b9;
                }
            }
            return true;
        }

        public boolean b(byte[] bArr, int i8) {
            if (bArr == null || i8 <= 0) {
                return false;
            }
            this.f3201c = i8;
            this.f3200b = 0;
            byte b9 = bArr[0];
            int i9 = 1;
            for (int i10 = 1; i10 < i8; i10++) {
                if (bArr[i10] == b9) {
                    i9++;
                } else {
                    if (!a(b9, i9)) {
                        return false;
                    }
                    b9 = bArr[i10];
                    i9 = 1;
                }
            }
            return a(b9, i9);
        }
    }

    /* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
    protected static class g {

        /* renamed from: a, reason: collision with root package name */
        public final int f3202a;

        /* renamed from: b, reason: collision with root package name */
        protected int f3203b;

        /* renamed from: c, reason: collision with root package name */
        protected final c f3204c = new c();

        /* renamed from: d, reason: collision with root package name */
        protected final d f3205d = new d();

        /* renamed from: e, reason: collision with root package name */
        protected final e f3206e = new e();

        public g(int i8, int i9) {
            this.f3202a = i8 & 32816;
        }

        protected boolean a(boolean z8, int i8) {
            if ((this.f3203b & 32768) != 0 && !this.f3204c.e(z8, i8)) {
                this.f3203b &= -32769;
            }
            if ((this.f3203b & 16) != 0 && !this.f3205d.e(z8, i8)) {
                this.f3203b &= -17;
            }
            if ((this.f3203b & 32) != 0 && !this.f3206e.e(z8, i8)) {
                this.f3203b &= -33;
            }
            return this.f3203b != 0;
        }

        public h b(byte[] bArr, int i8, byte[] bArr2, int i9) {
            int i10 = 0;
            if (i8 >= i9) {
                while (i10 < i9) {
                    bArr[i10] = (byte) (bArr[i10] ^ bArr2[i10]);
                    i10++;
                }
            } else {
                while (i10 < i8) {
                    bArr[i10] = (byte) (bArr[i10] ^ bArr2[i10]);
                    i10++;
                }
                DzArrays.e(bArr, i8, bArr2, i8, i9);
                i8 = i9;
            }
            return c(bArr, i8);
        }

        /* JADX WARN: Code restructure failed: missing block: B:10:0x002d, code lost:
        
            r2 = r2 + 1;
         */
        /* JADX WARN: Removed duplicated region for block: B:8:0x0090 A[LOOP:1: B:3:0x000a->B:8:0x0090, LOOP_END] */
        /* JADX WARN: Removed duplicated region for block: B:9:0x002d A[EDGE_INSN: B:9:0x002d->B:10:0x002d BREAK  A[LOOP:1: B:3:0x000a->B:8:0x0090], SYNTHETIC] */
        /*
            Code decompiled incorrectly, please refer to instructions dump.
        */
        public h c(byte[] bArr, int i8) {
            d(i8);
            int i9 = 0;
            boolean z8 = false;
            int i10 = 0;
            do {
                int i11 = 128;
                while (true) {
                    if ((bArr[i9] & i11) != 0) {
                        if (!z8) {
                            if (!a(false, i10)) {
                                return null;
                            }
                            z8 = true;
                            i10 = 1;
                            if (i11 != 1) {
                                break;
                            }
                            i11 >>>= 1;
                        }
                        i10++;
                        if (i11 != 1) {
                        }
                    } else {
                        if (z8) {
                            if (!a(true, i10)) {
                                return null;
                            }
                            z8 = false;
                            i10 = 1;
                            if (i11 != 1) {
                            }
                        }
                        i10++;
                        if (i11 != 1) {
                        }
                    }
                }
            } while (i9 < i8);
            if (z8 && !a(true, i10)) {
                return null;
            }
            int i12 = this.f3203b;
            if ((32768 & i12) != 0 && (((i12 & 16) == 0 || this.f3204c.b() <= this.f3205d.b()) && ((this.f3203b & 32) == 0 || this.f3204c.b() <= this.f3206e.b()))) {
                return this.f3204c;
            }
            int i13 = this.f3203b;
            if ((i13 & 32) != 0 && ((i13 & 16) == 0 || this.f3206e.b() <= this.f3205d.b())) {
                return this.f3206e;
            }
            if ((this.f3203b & 16) != 0) {
                return this.f3205d;
            }
            return null;
        }

        protected void d(int i8) {
            int i9 = this.f3202a;
            this.f3203b = i9;
            if ((i9 & 32768) != 0) {
                this.f3204c.d(i8);
            }
            if ((this.f3203b & 16) != 0) {
                this.f3205d.d(i8);
            }
            if ((this.f3203b & 32) != 0) {
                this.f3206e.d(i8);
            }
        }
    }

    /* compiled from: r8-map-id-a9401bf97a80db98386e1be17a9cc15e48f4b7b28def944626c1e855004c7afa */
    protected static abstract class h {

        /* renamed from: a, reason: collision with root package name */
        public byte[] f3207a;

        /* renamed from: b, reason: collision with root package name */
        protected int f3208b;

        /* renamed from: c, reason: collision with root package name */
        protected int f3209c;

        protected h() {
        }

        public abstract int a();

        public int b() {
            return ((this.f3208b * a()) + 7) / 8;
        }

        public int c() {
            return this.f3208b;
        }

        public void d(int i8) {
            this.f3209c = i8;
            this.f3208b = 0;
            this.f3207a = new byte[i8 + 2];
        }
    }

    public BitmapPackage(BluetoothUtils.c cVar, b.c cVar2) {
        boolean e9 = com.dothantech.data.b.e();
        this.f3146a = e9;
        this.f3148b = f3145e0 && e9;
        this.f3159k = 48;
        this.f3160l = 0;
        this.f3161m = DzBitmap.Direction.Normal;
        this.f3162n = 0;
        this.f3163o = 0;
        this.f3164p = 192;
        this.f3174z = 0;
        this.A = 0;
        this.B = 0;
        this.C = 0;
        this.F = 0;
        this.G = 0;
        this.H = 0;
        this.I = 0;
        this.M = 0;
        this.N = 0;
        this.O = 0;
        this.P = 0;
        this.Q = 0;
        this.R = 0;
        this.S = 0;
        this.T = 0;
        this.U = 0;
        this.V = 0;
        this.W = 0;
        this.X = 0;
        this.Y = 0;
        this.Z = 0;
        this.f3147a0 = 0;
        this.f3149b0 = 0;
        this.f3151c0 = 0;
        this.f3153e = cVar;
        this.f3154f = cVar2;
        this.f3156h = cVar.f2675b;
        this.f3155g = cVar2.E;
        this.f3157i = cVar2.f4199g;
        this.f3158j = cVar2.f4200h;
        this.f3165q = LineAction.None;
    }

    protected boolean a() {
        int i8 = a.f3179a[this.f3165q.ordinal()];
        if (i8 == 1) {
            i(this.f3166r + this.I);
        } else {
            if (i8 != 2) {
                return false;
            }
            q();
            i(this.I);
        }
        this.f3165q = LineAction.None;
        short s8 = this.f3156h;
        if (s8 == 16) {
            o(new byte[]{12});
        } else if (s8 != 303) {
            j((byte) 40);
        } else {
            o(new byte[]{29, 86, 66, 0});
        }
        int c9 = this.M + c();
        i0 i0Var = f3144d0;
        if (i0Var.c()) {
            i0Var.a("Line  Bytes  : " + this.f3159k);
            i0Var.a("Image Lines  : " + c9);
            if (this.D) {
                i0Var.a("Anti  Color  : YES");
            }
            i0Var.a("Buffer Count : " + this.f3152d.e());
            i0Var.a(" MaxSfDots   : " + this.f3174z);
            i0Var.a(" MaxLEDots   : " + this.A);
            i0Var.a(" MinSfDots   : " + this.B);
            i0Var.a(" TotalDots   : " + this.C);
            i0Var.a(" =============");
            i0Var.a(" SumLines    : " + this.M);
            i0Var.a(" SumPrints   : " + this.N);
            if (this.f3146a) {
                i0Var.a(" SumRLECs    : " + this.O);
                i0Var.a(" SumRLE4Xs   : " + this.P);
                i0Var.a(" SumRLE4Ds   : " + this.Q);
                i0Var.a(" SumRLE5Xs   : " + this.R);
                i0Var.a(" SumRLE5Ds   : " + this.S);
                i0Var.a(" SumRLE6Xs   : " + this.T);
                i0Var.a(" SumRLE6Ds   : " + this.U);
                i0Var.a(" SumRepeats  : " + this.V);
                i0Var.a(" =============");
                i0Var.a(" RLECSaved   : " + this.W);
                i0Var.a(" RLE4XSaved  : " + this.X);
                i0Var.a(" RLE4DSaved  : " + this.Y);
                i0Var.a(" RLE5XSaved  : " + this.Z);
                i0Var.a(" RLE5DSaved  : " + this.f3147a0);
                i0Var.a(" RLE6XSaved  : " + this.f3149b0);
                i0Var.a(" RLE6DSaved  : " + this.f3151c0);
            }
        }
        int k8 = this.f3152d.k();
        i0Var.j(" Total Bytes : " + k8);
        int i9 = this.f3159k * c9;
        i0Var.j(String.format(" Dot Percent : %.2f%%", Double.valueOf((((double) this.C) * 100.0d) / ((double) (i9 * 8)))));
        i0Var.j(" Image Bytes : " + i9);
        i0Var.j(String.format(" Zip Percent : %.2f%%", Double.valueOf((((double) k8) * 100.0d) / ((double) i9))));
        i0Var.j("End   BitmapPackage");
        return true;
    }

    public com.dothantech.data.c b() {
        b bVar = this.f3150c;
        if (bVar == null) {
            return null;
        }
        return bVar;
    }

    protected int c() {
        return this.N + this.O + this.P + this.Q + this.R + this.S + this.T + this.U;
    }

    protected boolean d(int i8) {
        int i9 = a.f3179a[this.f3165q.ordinal()];
        if (i9 == 1) {
            this.f3166r += i8;
            return true;
        }
        if (i9 != 2) {
            return false;
        }
        q();
        this.f3168t = null;
        this.f3167s = 0;
        this.f3166r = i8;
        this.f3165q = LineAction.Line;
        return true;
    }

    /* JADX WARN: Removed duplicated region for block: B:31:0x016b  */
    /* JADX WARN: Removed duplicated region for block: B:45:0x01b0  */
    /* JADX WARN: Removed duplicated region for block: B:48:0x01bf  */
    /* JADX WARN: Removed duplicated region for block: B:51:0x01c1  */
    /* JADX WARN: Removed duplicated region for block: B:54:0x0174  */
    /* JADX WARN: Removed duplicated region for block: B:71:0x0095  */
    /* JADX WARN: Removed duplicated region for block: B:85:0x00cf  */
    /*
        Code decompiled incorrectly, please refer to instructions dump.
    */
    protected boolean e(Bitmap bitmap) {
        Bitmap bitmap2;
        int i8;
        int i9;
        int max;
        int i10;
        int i11;
        int i12;
        int i13;
        int i14;
        int max2;
        int max3;
        int min;
        int i15;
        int i16;
        int i17;
        boolean z8;
        short s8;
        int i18;
        if (bitmap == null) {
            return false;
        }
        if (this.E) {
            bitmap2 = DzBitmap.o(bitmap, 0);
            if (bitmap2 == null) {
                return false;
            }
        } else {
            bitmap2 = bitmap;
        }
        Bitmap e9 = DzBitmap.e(bitmap2, this.f3161m, Bitmap.Config.ARGB_8888);
        if (e9 == null) {
            return false;
        }
        if (bitmap2 != bitmap && bitmap2 != e9) {
            bitmap2.recycle();
        }
        int width = e9.getWidth();
        int height = e9.getHeight();
        int i19 = this.F;
        int i20 = width + i19 + this.G;
        int i21 = this.f3158j;
        int i22 = i20 - i21;
        if (i22 > 0) {
            int i23 = this.f3160l;
            if ((i23 & 512) != 0) {
                i22 /= 2;
            } else if ((i23 & 1024) != 0) {
                i22 = 0;
            }
            int i24 = (i19 - i22) + this.f3162n;
            if (i24 >= 0) {
                i18 = 0;
            } else {
                i18 = -i24;
                i24 = 0;
            }
            int min2 = Math.min(i24, i21);
            min = Math.min(i18, width);
            max3 = Math.min(i21 - min2, width - min);
            max2 = min2;
            max = i21;
        } else {
            int i25 = this.f3160l;
            if ((i25 & 512) != 0) {
                i9 = Math.abs(this.f3162n) * 2;
            } else if ((i25 & 1024) != 0) {
                i9 = this.f3162n;
            } else {
                i8 = i20 - this.f3162n;
                int i26 = this.f3158j;
                int i27 = i8 - i26;
                max = Math.max(Math.min(i8, i26), 0);
                i10 = this.f3162n;
                if (i10 < 0) {
                    int i28 = this.f3160l;
                    if ((i28 & 512) != 0) {
                        i22 /= 2;
                        i15 = (this.F + (i10 * 2)) - (i27 > 0 ? i27 / 2 : 0);
                        i17 = this.G;
                    } else if ((i28 & 1024) != 0) {
                        i15 = this.F + i10;
                        i17 = this.G;
                    } else {
                        i15 = this.F;
                        i16 = this.G + width;
                        int i29 = i16 - i10;
                        int min3 = Math.min(i15, this.f3158j);
                        max3 = Math.max(Math.min(i29, width), 0);
                        max2 = min3;
                        min = 0;
                    }
                    i16 = (i17 + width) - i22;
                    int i292 = i16 - i10;
                    int min32 = Math.min(i15, this.f3158j);
                    max3 = Math.max(Math.min(i292, width), 0);
                    max2 = min32;
                    min = 0;
                } else {
                    int i30 = this.f3160l;
                    if ((i30 & 512) != 0) {
                        i22 /= 2;
                        i11 = this.F;
                    } else if ((i30 & 1024) != 0) {
                        i12 = this.F;
                        i13 = i12 + i10;
                        i14 = width + i12 + i10;
                        int i31 = -(i12 + i10);
                        max2 = Math.max(Math.min(i13, this.F), 0);
                        max3 = Math.max(Math.min(i14, width), 0);
                        min = Math.min(Math.max(i31, 0), width);
                    } else {
                        i11 = this.F;
                    }
                    i13 = (i11 - i22) + i10;
                    i14 = ((width + i11) - i22) + i10;
                    i12 = i11 - i22;
                    int i312 = -(i12 + i10);
                    max2 = Math.max(Math.min(i13, this.F), 0);
                    max3 = Math.max(Math.min(i14, width), 0);
                    min = Math.min(Math.max(i312, 0), width);
                }
            }
            i8 = i20 + i9;
            int i262 = this.f3158j;
            int i272 = i8 - i262;
            max = Math.max(Math.min(i8, i262), 0);
            i10 = this.f3162n;
            if (i10 < 0) {
            }
        }
        int i32 = (max + 7) / 8;
        this.f3159k = i32;
        if (this.f3156h != 303) {
            m((byte) 39, (short) i32, true);
        } else {
            int i33 = (this.f3153e.f2682i - max) / 2;
            if (i33 > 0) {
                z8 = true;
                int i34 = ((int) (i33 / (r11.f2681h / 25.4d))) + c1.f8798s;
                if (i34 > 255) {
                    i34 = 255;
                }
                o(new byte[]{26, 55, d0.f(i34)});
                int min4 = Math.min(this.f3163o, 0) + height + this.H + this.I;
                s8 = this.f3156h;
                if (s8 != 16) {
                    l((byte) 38, (byte) -64, d0.d(min4), d0.f(min4));
                } else if (s8 != 303) {
                    m((byte) 38, (short) min4, z8);
                }
                this.J = ((this.f3155g & 128) == 0 && this.f3148b) ? new f(this.f3159k) : null;
                int i35 = this.f3155g;
                g gVar = ((32816 & i35) == 0 && this.f3148b) ? new g(i35, this.f3159k) : null;
                this.K = gVar;
                this.L = gVar != null ? new g(this.f3155g, this.f3159k) : null;
                b bVar = new b(e9, e9 == bitmap, min, Math.max(-this.f3163o, 0), width, height, max2, max3);
                this.f3150c = bVar;
                return bVar.f(true);
            }
        }
        z8 = true;
        int min42 = Math.min(this.f3163o, 0) + height + this.H + this.I;
        s8 = this.f3156h;
        if (s8 != 16) {
        }
        this.J = ((this.f3155g & 128) == 0 && this.f3148b) ? new f(this.f3159k) : null;
        int i352 = this.f3155g;
        if ((32816 & i352) == 0) {
        }
        this.K = gVar;
        this.L = gVar != null ? new g(this.f3155g, this.f3159k) : null;
        b bVar2 = new b(e9, e9 == bitmap, min, Math.max(-this.f3163o, 0), width, height, max2, max3);
        this.f3150c = bVar2;
        return bVar2.f(true);
    }

    public boolean f(Bitmap bitmap, Bundle bundle) {
        v(bundle);
        return e(bitmap);
    }

    protected boolean g(byte[] bArr) {
        return h(bArr, 1);
    }

    protected boolean h(byte[] bArr, int i8) {
        if (this.f3165q == LineAction.None) {
            return false;
        }
        int min = Math.min(bArr.length, this.f3159k) - 1;
        while (min >= 0 && bArr[min] == 0) {
            min--;
        }
        if (min < 0) {
            return d(i8);
        }
        int i9 = min + 1;
        int i10 = a.f3179a[this.f3165q.ordinal()];
        if (i10 == 1) {
            i(this.f3166r);
        } else {
            if (i10 != 2) {
                return false;
            }
            if (this.f3167s == i9 && DzArrays.j(this.f3168t, bArr, 0, i9)) {
                this.f3166r += i8;
                return true;
            }
            q();
        }
        this.f3168t = bArr;
        this.f3167s = i9;
        this.f3166r = i8;
        this.f3165q = LineAction.Print;
        return true;
    }

    protected void i(int i8) {
        if (i8 <= 0) {
            return;
        }
        r(0, i8);
        this.M += i8;
        short s8 = this.f3156h;
        if (s8 == 16 || s8 == 303) {
            while (i8 >= 255) {
                n(com.dothantech.data.b.f(27, 74, -1));
                i8 -= 255;
            }
            if (i8 > 0) {
                n(com.dothantech.data.b.f(27, 74, (byte) i8));
            }
        } else {
            while (i8 > 16383) {
                m((byte) 34, (short) 16383, true);
                i8 -= 16384;
            }
            if (i8 > 0) {
                if (!this.f3146a || i8 > 255) {
                    m((byte) 34, (short) (i8 - 1), true);
                } else {
                    n(com.dothantech.data.b.f(27, 74, (byte) i8));
                }
            }
        }
        this.f3170v = null;
        this.f3169u = 0;
    }

    protected void j(byte b9) {
        n(new com.dothantech.data.b(b9));
    }

    protected void k(byte b9, byte b10) {
        n(new com.dothantech.data.b(b9, b10));
    }

    protected void l(byte b9, byte b10, byte b11, byte b12) {
        n(new com.dothantech.data.b(b9, b10, b11, b12));
    }

    protected void m(byte b9, short s8, boolean z8) {
        n(new com.dothantech.data.b(b9, s8, z8));
    }

    protected void n(com.dothantech.data.b bVar) {
        this.f3152d.g(bVar);
    }

    protected void o(byte[] bArr) {
        p(bArr, bArr.length);
    }

    protected void p(byte[] bArr, int i8) {
        this.f3152d.j(bArr, i8);
    }

    protected void q() {
        int i8;
        int i9;
        char c9;
        int b9;
        int i10;
        byte[] bArr;
        int i11;
        f fVar;
        int i12 = this.f3166r;
        if (i12 <= 0) {
            return;
        }
        byte[] bArr2 = this.f3168t;
        int i13 = 0;
        while (true) {
            i8 = this.f3167s;
            if (i13 >= i8 || bArr2[i13] != 0) {
                break;
            } else {
                i13++;
            }
        }
        int i14 = i8 - i13;
        int i15 = 0;
        for (int i16 = i13; i16 < this.f3167s; i16++) {
            i15 += k.a(bArr2[i16]);
        }
        r(i15, i12);
        if (this.f3148b) {
            int i17 = (i13 >= 192 ? 4 : 3) + (i14 >= 192 ? 2 : 1) + i14;
            int i18 = this.f3167s;
            if (i18 < 5 || (fVar = this.J) == null || !fVar.b(bArr2, i18)) {
                i9 = Integer.MAX_VALUE;
            } else {
                int i19 = this.J.f3200b;
                i9 = i19 + (i19 >= 192 ? 4 : 3);
            }
            g gVar = this.K;
            h hVar = null;
            h c10 = (gVar == null || (i11 = this.f3167s) < 5) ? null : gVar.c(bArr2, i11);
            if (c10 == null) {
                b9 = Integer.MAX_VALUE;
                c9 = 1;
            } else {
                c9 = 1;
                b9 = c10.b() + (c10.c() >= 192 ? 4 : 3);
            }
            g gVar2 = this.L;
            if (gVar2 != null && (i10 = this.f3167s) >= 5 && (bArr = this.f3170v) != null) {
                hVar = gVar2.b(bArr, this.f3169u, bArr2, i10);
            }
            h hVar2 = hVar;
            int b10 = hVar2 != null ? hVar2.b() + (hVar2.c() >= 192 ? 4 : 3) : Integer.MAX_VALUE;
            if (i9 < i17 && i9 <= b9 && i9 <= b10) {
                this.O += i12;
                this.W += i17 - i9;
                s(this.J);
            } else if (b9 < i17 && b9 <= b10) {
                int a9 = c10.a();
                if (a9 == 4) {
                    this.P += i12;
                    this.X += i17 - b9;
                    t((byte) 58, c10);
                } else if (a9 == 5) {
                    this.R += i12;
                    this.Z += i17 - b9;
                    t((byte) 44, c10);
                } else if (a9 == 6) {
                    this.T += i12;
                    this.f3149b0 += i17 - b9;
                    t((byte) 60, c10);
                }
            } else if (b10 < i17) {
                int a10 = hVar2.a();
                if (a10 == 4) {
                    this.Q += i12;
                    this.Y += i17 - b10;
                    t((byte) 59, hVar2);
                } else if (a10 == 5) {
                    this.S += i12;
                    this.f3147a0 += i17 - b10;
                    t((byte) 45, hVar2);
                } else if (a10 == 6) {
                    this.U += i12;
                    this.f3151c0 += i17 - b10;
                    t((byte) 61, hVar2);
                }
            } else {
                this.N += i12;
                byte[] bArr3 = new byte[i14 + 6];
                bArr3[0] = com.dothantech.data.b.f3254c;
                bArr3[c9] = 43;
                int i20 = com.dothantech.data.b.i(bArr3, com.dothantech.data.b.i(bArr3, 2, i13), i14);
                DzArrays.e(bArr3, i20, bArr2, i13, this.f3167s);
                n(com.dothantech.data.b.g(bArr3, i20 + i14));
            }
            u(i12 - 1);
        } else {
            this.N += i12;
            short s8 = this.f3156h;
            if (s8 == 16) {
                byte[] bArr4 = new byte[i14 + 6];
                bArr4[0] = com.dothantech.data.b.f3254c;
                bArr4[1] = 43;
                int i21 = com.dothantech.data.b.i(bArr4, com.dothantech.data.b.i(bArr4, 2, i13), i14);
                DzArrays.e(bArr4, i21, bArr2, i13, this.f3167s);
                n(com.dothantech.data.b.g(bArr4, i21 + i14));
                u(i12 - 1);
            } else if (s8 != 303) {
                byte[] bArr5 = new byte[4];
                if (i12 > 16383) {
                    n(new com.dothantech.data.b(PublicSuffixDatabase.f11676i, bArr5, 0, com.dothantech.data.b.j(bArr5, com.dothantech.data.b.j(bArr5, 0, (short) 16383), (short) i13), bArr2, i13, this.f3167s));
                    u(i12 - 16384);
                } else if (i12 > 0) {
                    n(new com.dothantech.data.b(PublicSuffixDatabase.f11676i, bArr5, 0, com.dothantech.data.b.j(bArr5, com.dothantech.data.b.j(bArr5, 0, (short) (i12 - 1)), (short) i13), bArr2, i13, this.f3167s));
                }
            } else {
                int i22 = this.f3167s;
                byte[] bArr6 = new byte[i22 + 8];
                bArr6[0] = 29;
                bArr6[1] = 118;
                bArr6[2] = 48;
                bArr6[3] = 0;
                bArr6[4] = d0.f(i22);
                bArr6[5] = d0.d(this.f3167s);
                bArr6[6] = 1;
                bArr6[7] = 0;
                DzArrays.e(bArr6, 8, bArr2, 0, this.f3167s);
                for (int i23 = 0; i23 < i12; i23++) {
                    o(bArr6);
                }
            }
        }
        this.f3170v = this.f3168t;
        this.f3169u = this.f3167s;
    }

    protected void r(int i8, int i9) {
        int i10;
        int[] iArr;
        if (this.f3174z < i8) {
            this.f3174z = i8;
        } else if (i8 > 0 && ((i10 = this.B) == 0 || i10 > i8)) {
            this.B = i8;
        }
        int i11 = i8 * i9;
        this.C += i11;
        int i12 = 0;
        if (i9 >= this.f3171w.length) {
            while (true) {
                iArr = this.f3171w;
                if (i12 >= iArr.length) {
                    break;
                }
                iArr[i12] = i8;
                i12++;
            }
            this.f3172x = iArr.length * i8;
            if (this.A < i8) {
                this.A = i8;
                return;
            }
            return;
        }
        this.f3172x += i11;
        for (int i13 = 0; i13 < i9; i13++) {
            int i14 = this.f3172x;
            int[] iArr2 = this.f3171w;
            int i15 = this.f3173y;
            this.f3172x = i14 - iArr2[i15];
            iArr2[i15] = i8;
            int i16 = i15 + 1;
            this.f3173y = i16;
            if (i16 >= iArr2.length) {
                this.f3173y = 0;
            }
        }
        int length = this.f3172x / this.f3171w.length;
        if (this.A < length) {
            this.A = length;
        }
    }

    protected void s(f fVar) {
        int i8 = fVar.f3200b;
        byte[] bArr = new byte[i8 + 8];
        bArr[0] = com.dothantech.data.b.f3254c;
        bArr[1] = 41;
        int i9 = com.dothantech.data.b.i(bArr, 2, i8);
        DzArrays.e(bArr, i9, fVar.f3199a, 0, i8);
        n(com.dothantech.data.b.g(bArr, i9 + i8));
    }

    protected void t(byte b9, h hVar) {
        byte[] bArr = hVar.f3207a;
        int b10 = hVar.b();
        byte[] bArr2 = new byte[b10 + 8];
        bArr2[0] = com.dothantech.data.b.f3254c;
        bArr2[1] = b9;
        int i8 = com.dothantech.data.b.i(bArr2, 2, hVar.c());
        DzArrays.e(bArr2, i8, bArr, 0, b10);
        n(com.dothantech.data.b.g(bArr2, i8 + b10));
    }

    protected void u(int i8) {
        short s8;
        if (i8 <= 0) {
            return;
        }
        this.V += i8;
        byte[] bArr = {com.dothantech.data.b.f3254c, 46, 0, 0};
        short s9 = this.f3156h;
        if (s9 == 16) {
            s8 = 191;
        } else if (s9 == 303) {
            return;
        } else {
            s8 = 16383;
        }
        while (i8 > s8) {
            com.dothantech.data.b.j(bArr, 2, s8);
            n(com.dothantech.data.b.f(bArr));
            i8 -= s8 + 1;
        }
        if (i8 > 0) {
            n(com.dothantech.data.b.g(bArr, com.dothantech.data.b.j(bArr, 2, (short) (i8 - 1))));
        }
    }

    /* JADX WARN: Removed duplicated region for block: B:70:0x020c  */
    /* JADX WARN: Removed duplicated region for block: B:73:0x021d  */
    /* JADX WARN: Removed duplicated region for block: B:76:0x024b  */
    /* JADX WARN: Removed duplicated region for block: B:79:0x027f  */
    /* JADX WARN: Removed duplicated region for block: B:86:0x02d4  */
    /* JADX WARN: Removed duplicated region for block: B:91:0x0286  */
    /* JADX WARN: Removed duplicated region for block: B:92:0x0252  */
    /* JADX WARN: Removed duplicated region for block: B:93:0x0213  */
    /*
        Code decompiled incorrectly, please refer to instructions dump.
    */
    protected void v(Bundle bundle) {
        float f9;
        float f10;
        short s8;
        int i8;
        int i9;
        int i10;
        int i11;
        short s9;
        Bundle bundle2 = bundle == null ? new Bundle() : bundle;
        i0 i0Var = f3144d0;
        i0Var.j("Start BitmapPackage");
        if (i0Var.c()) {
            i0Var.a(bundle2.toString());
            i0Var.a("PrinterDPI   : " + this.f3157i);
            i0Var.a("PrinterWidth : " + this.f3158j);
        }
        this.f3152d = new d.a();
        int i12 = bundle2.getInt("PAGE_KEY", 0);
        byte b9 = bundle2.getBoolean("PRINT_SEPARATE_LINE");
        short s10 = this.f3156h;
        if (s10 != 16) {
            if (s10 != 303) {
                byte[] bArr = new byte[8];
                bArr[0] = (byte) (i12 >>> 8);
                bArr[1] = (byte) (i12 & 255);
                bArr[6] = b9;
                n(new com.dothantech.data.b((byte) 32, bArr));
            } else {
                o(new byte[]{27, 64, 26, 56, 1, 26, 57, 1, 26, 58, 2});
            }
        }
        this.D = bundle2.getBoolean("ANTI_COLOR", false);
        this.E = bundle2.getBoolean("HOR_FLIP", false);
        int i13 = bundle2.getInt("LEFT_MARGIN_01MM", -1);
        this.F = Math.max(0, i13 < 0 ? bundle2.getInt("LEFT_MARGIN_PX", -1) : Math.round((i13 / 100.0f) * (this.f3157i / 25.4f)));
        int i14 = bundle2.getInt("RIGHT_MARGIN_01MM", -1);
        this.G = Math.max(0, i14 < 0 ? bundle2.getInt("RIGHT_MARGIN_PX", -1) : Math.round((i14 / 100.0f) * (this.f3157i / 25.4f)));
        int i15 = bundle2.getInt("TOP_MARGIN_01MM", -1);
        this.H = Math.max(0, i15 < 0 ? bundle2.getInt("TOP_MARGIN_PX", -1) : Math.round((i15 / 100.0f) * (this.f3157i / 25.4f)));
        int i16 = bundle2.getInt("BOTTOM_MARGIN_01MM", -1);
        this.I = Math.max(0, i16 < 0 ? bundle2.getInt("BOTTOM_MARGIN_PX", -1) : Math.round((i16 / 100.0f) * (this.f3157i / 25.4f)));
        int i17 = bundle2.getInt("PRINT_DENSITY", -1);
        if (i17 >= 0 && i17 < 255 && this.f3154f.f4208m > i17) {
            if (this.f3153e.f2675b != 303) {
                k((byte) 67, (byte) i17);
            } else {
                k((byte) 67, (byte) (i17 + 1));
            }
        }
        int i18 = bundle2.getInt("PRINT_SPEED", -1);
        if (i18 >= 0 && i18 < 255 && this.f3154f.f4212q > i18) {
            if (this.f3153e.f2675b != 303) {
                k((byte) 68, (byte) i18);
            } else {
                k((byte) 68, (byte) (i18 + 1));
            }
        }
        int i19 = bundle2.getInt("GAP_TYPE", -1);
        if (i19 >= 0 && i19 < 255) {
            if (this.f3153e.f2675b != 303) {
                k((byte) 66, (byte) i19);
            }
            if (i19 != 0 && (s9 = this.f3153e.f2675b) != 16 && s9 != 303) {
                int i20 = bundle2.getInt("GAP_LENGTH_01MM", -1);
                if (i20 < 0 && (i20 = bundle2.getInt("GAP_LENGTH_PX", -1)) >= 0) {
                    i20 = (i20 * 2540) / this.f3157i;
                }
                if (i20 >= 0) {
                    if (i20 > 16383) {
                        int min = Math.min(i20, 4194303);
                        f9 = 25.4f;
                        f10 = 100.0f;
                        n(new com.dothantech.data.b((byte) 69, new byte[]{(byte) ((min >>> 16) | 192), (byte) ((min >>> 8) & 255), (byte) (min & 255)}));
                    } else {
                        f9 = 25.4f;
                        f10 = 100.0f;
                        m((byte) 69, (short) i20, true);
                    }
                    s8 = this.f3153e.f2675b;
                    if (s8 != 16 && s8 != 303 && (i11 = bundle2.getInt("MOTOR_MODE", -1)) >= 0 && i11 < 255) {
                        k((byte) 71, (byte) i11);
                    }
                    this.f3160l = bundle2.getInt("PRINT_ALIGNMENT", this.f3155g & 1536);
                    i8 = bundle2.getInt("PRINT_DIRECTION", -1);
                    if (i8 < 0) {
                        this.f3161m = DzBitmap.Direction.d(i8);
                    } else {
                        this.f3161m = DzBitmap.Direction.Normal;
                    }
                    if ((this.f3155g & 16384) != 0) {
                        this.f3161m = this.f3161m.c(DzBitmap.Direction.Rotate180);
                    }
                    i0Var.a("Direction    : " + this.f3161m.toString());
                    int i21 = bundle2.getInt("HORIZONTAL_OFFSET_01MM", Integer.MIN_VALUE);
                    this.f3162n = i21 != Integer.MIN_VALUE ? bundle2.getInt("HORIZONTAL_OFFSET_PX", 0) : Math.round((i21 / f10) * (this.f3157i / f9));
                    i0Var.a("HorOffset    : " + this.f3162n);
                    int i22 = bundle2.getInt("VERTICAL_OFFSET_01MM", Integer.MIN_VALUE);
                    this.f3163o = i22 != Integer.MIN_VALUE ? bundle2.getInt("VERTICAL_OFFSET_PX", 0) : Math.round((i22 / f10) * (this.f3157i / f9));
                    i0Var.a("VerOffset    : " + this.f3163o);
                    i9 = bundle2.getInt("IMAGE_THRESHOLD", -1);
                    if (i9 > 0 || i9 >= 255) {
                        this.f3164p = 192;
                    } else {
                        this.f3164p = i9;
                    }
                    i0Var.a("Threshold    : " + this.f3164p);
                    i10 = this.f3163o;
                    if (i10 > 0) {
                        this.H += i10;
                        this.f3163o = 0;
                    }
                    this.f3165q = LineAction.Line;
                    this.f3166r = this.H;
                    this.f3170v = null;
                    this.f3168t = null;
                    this.f3169u = 0;
                    this.f3167s = 0;
                    this.f3171w = new int[(int) (((this.f3157i * 3) / 25.4d) + 0.5d)];
                    this.f3172x = 0;
                    this.f3173y = 0;
                    this.f3174z = 0;
                    this.A = 0;
                    this.B = 0;
                    this.C = 0;
                    this.M = 0;
                    this.N = 0;
                    this.O = 0;
                    this.P = 0;
                    this.Q = 0;
                    this.R = 0;
                    this.S = 0;
                    this.T = 0;
                    this.U = 0;
                    this.V = 0;
                    this.W = 0;
                    this.X = 0;
                    this.Y = 0;
                    this.Z = 0;
                    this.f3147a0 = 0;
                    this.f3149b0 = 0;
                    this.f3151c0 = 0;
                }
            }
        }
        f9 = 25.4f;
        f10 = 100.0f;
        s8 = this.f3153e.f2675b;
        if (s8 != 16) {
            k((byte) 71, (byte) i11);
        }
        this.f3160l = bundle2.getInt("PRINT_ALIGNMENT", this.f3155g & 1536);
        i8 = bundle2.getInt("PRINT_DIRECTION", -1);
        if (i8 < 0) {
        }
        if ((this.f3155g & 16384) != 0) {
        }
        i0Var.a("Direction    : " + this.f3161m.toString());
        int i212 = bundle2.getInt("HORIZONTAL_OFFSET_01MM", Integer.MIN_VALUE);
        this.f3162n = i212 != Integer.MIN_VALUE ? bundle2.getInt("HORIZONTAL_OFFSET_PX", 0) : Math.round((i212 / f10) * (this.f3157i / f9));
        i0Var.a("HorOffset    : " + this.f3162n);
        int i222 = bundle2.getInt("VERTICAL_OFFSET_01MM", Integer.MIN_VALUE);
        this.f3163o = i222 != Integer.MIN_VALUE ? bundle2.getInt("VERTICAL_OFFSET_PX", 0) : Math.round((i222 / f10) * (this.f3157i / f9));
        i0Var.a("VerOffset    : " + this.f3163o);
        i9 = bundle2.getInt("IMAGE_THRESHOLD", -1);
        if (i9 > 0) {
        }
        this.f3164p = 192;
        i0Var.a("Threshold    : " + this.f3164p);
        i10 = this.f3163o;
        if (i10 > 0) {
        }
        this.f3165q = LineAction.Line;
        this.f3166r = this.H;
        this.f3170v = null;
        this.f3168t = null;
        this.f3169u = 0;
        this.f3167s = 0;
        this.f3171w = new int[(int) (((this.f3157i * 3) / 25.4d) + 0.5d)];
        this.f3172x = 0;
        this.f3173y = 0;
        this.f3174z = 0;
        this.A = 0;
        this.B = 0;
        this.C = 0;
        this.M = 0;
        this.N = 0;
        this.O = 0;
        this.P = 0;
        this.Q = 0;
        this.R = 0;
        this.S = 0;
        this.T = 0;
        this.U = 0;
        this.V = 0;
        this.W = 0;
        this.X = 0;
        this.Y = 0;
        this.Z = 0;
        this.f3147a0 = 0;
        this.f3149b0 = 0;
        this.f3151c0 = 0;
    }
}
