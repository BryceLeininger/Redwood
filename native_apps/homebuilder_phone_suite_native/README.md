# Homebuilder Phone Suite Native

This is a Capacitor shell that packages the existing phone suite into a native mobile container.

The native app loads a local shell and then points an embedded workspace at your running backend.

## Start the backend first

From the repo root:

```bash
run_homebuilder_phone_suite.bat
```

Or:

```bash
python -m agent_factory.homebuilder_phone_suite_server --host 0.0.0.0 --port 8790
```

## Install native dependencies

```bash
cd native_apps/homebuilder_phone_suite_native
npm install
```

## Generate platform projects

```bash
npm run add:android
npm run add:ios
```

## Sync changes

```bash
npm run sync
```

## Open the native projects

```bash
npm run open:android
npm run open:ios
```

## App flow

1. Launch the native app.
2. Enter the backend suite URL, for example `http://192.168.1.25:8790`.
3. Tap `Connect`.
4. Switch between `Underwrite`, `Scout`, and `Diligence`.

The app shell stores the backend URL locally on the device.
