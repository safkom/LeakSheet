#!/bin/bash
# Builds an unsigned .ipa for sideloading via AltStore/AltServer (no paid Apple
# Developer account needed — AltServer resigns the app with your free Apple ID
# on install). Run from anywhere; output lands in build/LeakSheet.ipa.
set -euo pipefail

cd "$(dirname "$0")"

export DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer

rm -rf build
xcodebuild -project LeakSheet.xcodeproj -scheme LeakSheet -configuration Release \
  -sdk iphoneos -destination "generic/platform=iOS" -derivedDataPath build/DerivedData \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" \
  build

APP_PATH="build/DerivedData/Build/Products/Release-iphoneos/LeakSheet.app"

mkdir -p build/Payload
rm -rf "build/Payload/LeakSheet.app"
cp -R "$APP_PATH" build/Payload/

rm -f build/LeakSheet.ipa
(cd build && zip -qr LeakSheet.ipa Payload)
rm -rf build/Payload

echo "Built build/LeakSheet.ipa"
