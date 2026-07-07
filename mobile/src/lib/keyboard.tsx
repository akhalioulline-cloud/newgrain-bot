import React, { useEffect, useState } from 'react';
import { Keyboard, KeyboardAvoidingView as RNKAV, Platform } from 'react-native';
import Constants from 'expo-constants';

// react-native-keyboard-controller = pixel-precise IME tracking (catches Gboard growing its
// suggestion strip mid-session, which fires NO React Native keyboard event). Native module →
// present only in EAS builds; in Expo Go we fall back to RN's events + a fudge constant.
let KC: any = null;
if (Constants.appOwnership !== 'expo') {
  try { KC = require('react-native-keyboard-controller'); } catch {}
}
export const kcActive = !!KC?.KeyboardProvider;

export function KeyboardProviderMaybe({ children }: { children: React.ReactNode }) {
  return kcActive ? <KC.KeyboardProvider>{children}</KC.KeyboardProvider> : <>{children}</>;
}

// composer wrapper: precise KAV when tracked natively; RN's KAV (iOS) / no-op (Android) otherwise
export function SmartKAV(props: any) {
  if (kcActive) return <KC.KeyboardAvoidingView behavior="padding" {...props} />;
  return <RNKAV behavior={Platform.OS === 'ios' ? 'padding' : undefined} {...props} />;
}

// {open, height} — from the precise tracker when available (updates on IME resize), else RN events
export function useKeyboardSmart() {
  const [kb, setKb] = useState({ open: false, height: 0 });
  useEffect(() => {
    if (kcActive) {
      const subs = [
        KC.KeyboardEvents.addListener('keyboardWillShow', (e: any) => setKb({ open: true, height: e.height })),
        KC.KeyboardEvents.addListener('keyboardDidShow', (e: any) => setKb({ open: true, height: e.height })),
        KC.KeyboardEvents.addListener('keyboardWillHide', () => setKb({ open: false, height: 0 })),
      ];
      return () => subs.forEach((s) => s.remove());
    }
    const showEvt = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvt = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const s = Keyboard.addListener(showEvt, (e: any) => setKb({ open: true, height: e?.endCoordinates?.height || 0 }));
    const h = Keyboard.addListener(hideEvt, () => setKb({ open: false, height: 0 }));
    return () => { s.remove(); h.remove(); };
  }, []);
  return kb;
}

// bottom margin for the floating composer while the keyboard is open:
// tracked natively → tiny gap (KAV pads exactly); iOS RN-KAV → 0; Expo Go Android → fudge
export function composerLift(height: number): number {
  if (kcActive) return 6;
  return Platform.OS === 'ios' ? 0 : height + 26;
}
