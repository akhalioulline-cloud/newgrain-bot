import { Platform } from 'react-native';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';

import { api } from './api';

// Show notifications even when the app is foregrounded (Android suppresses them by default).
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

// Register this device for push. Dormant in Expo Go (SDK 53+ can't receive remote push) and
// when no EAS projectId is configured; springs alive in the EAS build. Never throws.
export async function registerPush(): Promise<void> {
  try {
    if (Constants.appOwnership === 'expo') return;          // Expo Go — no remote push
    if (!Device.isDevice) return;                           // simulators can't receive push
    const projectId = (Constants.expoConfig as any)?.extra?.eas?.projectId;
    if (!projectId) return;                                 // pre-`eas init` builds

    const perm = await Notifications.getPermissionsAsync();
    let status = perm.status;
    if (status !== 'granted') {
      status = (await Notifications.requestPermissionsAsync()).status;
    }
    if (status !== 'granted') return;

    if (Platform.OS === 'android') {
      // fresh channel id: Android freezes a channel's importance after creation, so the old
      // 'default' (created by an earlier build) can't be raised — 'messages' starts loud
      await Notifications.setNotificationChannelAsync('messages', {
        name: 'Сообщения',
        importance: Notifications.AndroidImportance.MAX,
        sound: 'default',
        vibrationPattern: [0, 250, 250, 250],
        lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
      });
    }
    const token = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
    await api.postJson('/api/push/register', { token, platform: Platform.OS });
  } catch {
    // best-effort: push registration must never break login
  }
}

// Opening the app clears the icon badge + swipes delivered notifications off the tray.
export async function clearBadge(): Promise<void> {
  try {
    await Notifications.setBadgeCountAsync(0);
    await Notifications.dismissAllNotificationsAsync();
  } catch {}
}
