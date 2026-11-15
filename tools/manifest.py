import sys, json
from androguard.core.apk import APK

apk = APK(sys.argv[1])
print("PACKAGE     :", apk.get_package())
print("APP NAME    :", apk.get_app_name())
print("VERSION     :", apk.get_androidversion_name(), "/", apk.get_androidversion_code())
print("MIN/TARGET  :", apk.get_min_sdk_version(), "/", apk.get_target_sdk_version())
print()
print("=== PERMISSIONS ===")
for p in sorted(apk.get_permissions()):
    print("  ", p)
print()
print("=== ACTIVITIES ===")
for a in apk.get_activities():
    print("  ", a)
print()
print("=== SERVICES ===")
for s in apk.get_services():
    print("  ", s)
print()
print("=== RECEIVERS ===")
for r in apk.get_receivers():
    print("  ", r)
print()
print("=== PROVIDERS ===")
for p in apk.get_providers():
    print("  ", p)

a = apk.get_android_manifest_xml()
print()
print("=== INTENT FILTERS / DEEP LINKS ===")
for tag in ("activity",):
    for el in a.iter(tag):
        name = el.get("{http://schemas.android.com/apk/res/android}name")
        for data in el.iter("data"):
            attrs = {k.split("}")[-1]: v for k, v in data.attrib.items()}
            scheme = attrs.get("scheme")
            if scheme:
                print("  ", name, attrs)
