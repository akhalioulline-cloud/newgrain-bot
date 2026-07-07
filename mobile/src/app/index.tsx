import { createContext, useContext, useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  ActivityIndicator, Alert, Animated, AppState, FlatList, Image, Keyboard, KeyboardAvoidingView,
  Modal, PanResponder, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput,
  useColorScheme, useWindowDimensions, View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Constants from 'expo-constants';
import { BlurView } from 'expo-blur';
import * as ImagePicker from 'expo-image-picker';
import * as MediaLibrary from 'expo-media-library';
import { Ionicons } from '@expo/vector-icons';

import * as Updates from 'expo-updates';

import { api, getToken, setToken } from '@/lib/api';
import { registerPush, clearBadge } from '@/lib/push';

// human-readable build/update stamp for the chat-list footer — ends "which version is this
// phone actually running?" debugging forever
const VERSION_STAMP = (() => {
  const v = Constants.expoConfig?.version || '?';
  if (__DEV__) return `EAR ${v} · dev`;
  if (!Updates.isEnabled || Updates.isEmbeddedLaunch || !Updates.createdAt) return `EAR ${v} · базовая сборка`;
  const d = Updates.createdAt;
  return `EAR ${v} · обновлено ${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })} ${d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`;
})();

// dense rounded brand face; system-bundled on iOS, Roboto Black on Android — no font assets needed
const BRAND_FONT = Platform.select({ ios: 'Avenir Next', android: 'sans-serif-black', default: undefined });

// ─────────────────────────── theme ───────────────────────────
const LIGHT = {
  dark: false, blurTint: 'light' as 'light' | 'dark',
  gold: '#b9994b', text: '#1a1a1a', bg: '#faf7f1', line: '#e7e2d8', muted: '#9a8f7a',
  card: '#ffffff', cardAlt: '#f5f1e8', capsule: '#f3eee2',
  botPanel: '#faf4e6', botText: '#2a2418', botLabel: '#9a7b1e',
  avBot: '#1a1a1a', avPerson: '#e8dfc8', avPersonText: '#6b541f',
  headerBg: 'rgba(250,247,241,0.96)', hairline: 'rgba(120,90,30,0.12)', pressed: 'rgba(120,90,30,0.05)',
  media: '#dfe6d3', bubbleMine: '#1a1a1a', bubbleMineText: '#ffffff',
  pillOkBg: '#eaf3e2', pillOk: '#3b6d11', pillBadBg: '#fbeceb', pillBad: '#a32d2d',
};
const DARK: typeof LIGHT = {
  dark: true, blurTint: 'dark',
  gold: '#cbaa58', text: '#ece5d6', bg: '#151310', line: '#2e2a21', muted: '#948b76',
  card: '#211d16', cardAlt: '#2b261c', capsule: '#2b261c',
  botPanel: '#2a2413', botText: '#e6dcc4', botLabel: '#d8b968',
  avBot: '#000000', avPerson: '#3a3426', avPersonText: '#d9c795',
  headerBg: 'rgba(21,19,16,0.96)', hairline: 'rgba(255,255,255,0.08)', pressed: 'rgba(255,255,255,0.05)',
  media: '#262d1f', bubbleMine: '#453a1c', bubbleMineText: '#f4ecd9',
  pillOkBg: '#26331a', pillOk: '#9cc86a', pillBadBg: '#3a201e', pillBad: '#e08b83',
};
type Theme = typeof LIGHT;

const softShadow = {
  shadowColor: '#3c280a', shadowOpacity: 0.08, shadowRadius: 16, shadowOffset: { width: 0, height: 6 }, elevation: 3,
};

const makeStyles = (t: Theme) => StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: t.bg },
  logo: { fontFamily: BRAND_FONT, fontWeight: '900', letterSpacing: 0.8, color: t.text },
  off: { opacity: 0.5 },
  // login
  h1: { fontSize: 22, fontWeight: '600', marginTop: 18, color: t.text },
  lead: { fontSize: 14, color: t.muted, lineHeight: 20, marginTop: 6, marginBottom: 18 },
  fld: { fontSize: 13, color: t.muted, marginBottom: 6 },
  input: { borderWidth: 1, borderColor: t.line, borderRadius: 14, padding: 14, fontSize: 16, backgroundColor: t.card, color: t.text },
  code: { letterSpacing: 8, textAlign: 'center', fontSize: 22 },
  btn: { backgroundColor: t.gold, borderRadius: 24, padding: 15, alignItems: 'center', marginTop: 12, ...softShadow, shadowColor: t.gold, shadowOpacity: 0.35 },
  btnTxt: { color: '#fff', fontWeight: '600', fontSize: 15 },
  note: { marginTop: 12, fontSize: 13, color: t.text },
  help: { marginTop: 16, fontSize: 13, color: t.muted, lineHeight: 19 },
  // glass chrome
  headerGlass: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: t.hairline },
  headerRow: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12 },
  hdrRight: { marginLeft: 'auto', fontSize: 12, color: t.muted },
  // chat-list home
  chatRow: { flexDirection: 'row', alignItems: 'center', gap: 13, paddingHorizontal: 16, paddingVertical: 13 },
  rowAvLg: { width: 54, height: 54, borderRadius: 27, alignItems: 'center', justifyContent: 'center' },
  rowAv: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  avGroup: { backgroundColor: t.gold },
  avBot: { backgroundColor: t.avBot },
  avPerson: { backgroundColor: t.avPerson },
  avInitials: { color: t.avPersonText, fontFamily: BRAND_FONT, fontWeight: '800', fontSize: 17 },
  avInitialsSm: { color: '#fff', fontFamily: BRAND_FONT, fontWeight: '800', fontSize: 13 },
  unreadBadge: { minWidth: 21, height: 21, borderRadius: 11, backgroundColor: t.gold, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6, marginLeft: 8, marginTop: 3 },
  unreadTxt: { color: '#fff', fontSize: 12, fontWeight: '700' },
  flip: { transform: [{ scaleY: -1 }] },
  bubbleTime: { fontSize: 10.5, color: t.muted },
  bubbleMeta: { flexDirection: 'row', alignItems: 'center', gap: 3, marginTop: 3, alignSelf: 'flex-end' },
  daySep: { textAlign: 'center', color: t.muted, fontSize: 12, paddingVertical: 6 },
  viewerBg: { flex: 1, backgroundColor: 'rgba(0,0,0,0.96)' },
  viewerScroll: { flexGrow: 1 },
  viewerImg: { width: '100%', height: '100%' },
  viewerClose: { position: 'absolute', top: 54, right: 20, width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.15)', alignItems: 'center', justifyContent: 'center' },
  rowTop: { flexDirection: 'row', alignItems: 'center' },
  rowTitle: {
    fontSize: 16.5, color: t.text, flexShrink: 1,
    // Android's 'sans-serif-black' ignores fontWeight — pick a genuinely medium face there
    ...(Platform.OS === 'android' ? { fontFamily: 'sans-serif-medium' } : { fontFamily: BRAND_FONT, fontWeight: '500' as const }),
  },
  rowTime: { fontSize: 12, color: t.muted },
  versionStamp: { textAlign: 'center', color: t.muted, opacity: 0.6, fontSize: 11, paddingTop: 18 },
  rowPreview: { fontSize: 14, color: t.muted, marginTop: 3 },
  // chat header (inside an open conversation)
  chatHdrBg: { backgroundColor: t.headerBg },
  chatHdrRow: { flexDirection: 'row', alignItems: 'center', paddingLeft: 4, paddingRight: 12, paddingVertical: 7, gap: 9 },
  chatHdrAv: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  backBtn: { paddingVertical: 6, paddingRight: 6, flexDirection: 'row', alignItems: 'center' },
  backTxt: { fontSize: 17, color: t.gold, marginLeft: -3 },
  chatHdrTitle: { fontSize: 16, fontFamily: BRAND_FONT, fontWeight: '800', color: t.text, flexShrink: 1 },
  edgeStrip: { position: 'absolute', left: 0, bottom: 0, width: 30 },
  empty: { textAlign: 'center', color: t.muted, fontSize: 14, padding: 24, lineHeight: 20 },
  // post card
  post: { backgroundColor: t.card, borderRadius: 22, padding: 14, ...softShadow },
  phead: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 9 },
  pav: { width: 38, height: 38, borderRadius: 19, backgroundColor: t.avPerson, alignItems: 'center', justifyContent: 'center' },
  pavTxt: { color: t.avPersonText, fontWeight: '600', fontSize: 14 },
  pauth: { fontWeight: '600', color: t.text, fontSize: 14.5 },
  pmeta: { color: t.muted, fontSize: 12, marginTop: 1 },
  pbody: { fontSize: 15, lineHeight: 22, color: t.text },
  pmedia: { width: '100%', height: 210, borderRadius: 16, backgroundColor: t.media, marginTop: 10 },
  videoBox: { height: 140, borderRadius: 16, backgroundColor: t.media, alignItems: 'center', justifyContent: 'center', marginTop: 10 },
  botPanel: { backgroundColor: t.botPanel, borderRadius: 18, padding: 12, marginTop: 11 },
  botLabel: { flexDirection: 'row', alignItems: 'center', marginBottom: 4 },
  botLabelTxt: { color: t.botLabel, fontSize: 12.5, fontFamily: BRAND_FONT, fontWeight: '800', letterSpacing: 0.3 },
  botTxt: { fontSize: 13.5, lineHeight: 20, color: t.botText },
  actRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 11 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 11, paddingVertical: 6, borderRadius: 20 },
  pillOk: { backgroundColor: t.pillOkBg }, pillBad: { backgroundColor: t.pillBadBg },
  pillTxt: { fontSize: 12, fontWeight: '600' },
  cmtCount: { flexDirection: 'row', alignItems: 'center', marginLeft: 'auto' },
  cmtCountTxt: { fontSize: 12.5, color: t.muted },
  cmt: { backgroundColor: t.cardAlt, borderRadius: 16, padding: 10, marginTop: 8 },
  ca: { fontWeight: '600', color: t.text },
  cb: { fontSize: 13.5, lineHeight: 19, color: t.botText },
  cmtForm: { flexDirection: 'row', gap: 8, marginTop: 10, alignItems: 'center' },
  cinputSm: { flex: 1, borderRadius: 20, height: 40, paddingHorizontal: 14, fontSize: 15, backgroundColor: t.capsule, color: t.text },
  sendSm: { backgroundColor: t.gold, borderRadius: 20, width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  // dm bubbles
  bubble: { maxWidth: '86%', borderRadius: 20, paddingHorizontal: 14, paddingVertical: 10 },
  bubbleBot: { alignSelf: 'flex-start', backgroundColor: t.card, ...softShadow, shadowOpacity: 0.06 },
  bubbleUser: { alignSelf: 'flex-end', backgroundColor: t.bubbleMine },
  bubbleBotTxt: { fontSize: 15, lineHeight: 21, color: t.text },
  bubbleUserTxt: { fontSize: 15, lineHeight: 21, color: t.bubbleMineText },
  // wall (flat message stream)
  botWrap: { alignSelf: 'flex-start', maxWidth: '90%', backgroundColor: t.botPanel, borderRadius: 18, padding: 12 },
  wallTime: { fontSize: 10.5, color: t.muted, marginTop: 4 },
  wallAuthorSm: { fontSize: 12.5, fontWeight: '700', color: t.gold, marginBottom: 2 },
  verdictBtns: { flexDirection: 'row', gap: 6, marginLeft: 8 },
  vBtn: { width: 34, height: 30, borderRadius: 10, backgroundColor: t.cardAlt, alignItems: 'center', justifyContent: 'center' },
  vBtnOn: { backgroundColor: t.bg },
  replyQuote: { borderLeftWidth: 3, borderLeftColor: t.gold, paddingLeft: 8, marginBottom: 6, opacity: 0.9 },
  replyQuoteAuthor: { fontSize: 12.5, fontWeight: '700', color: t.gold },
  replyQuoteText: { fontSize: 13, color: t.muted },
  mentionBox: { marginHorizontal: 12, marginBottom: 6, borderRadius: 16, backgroundColor: t.card, overflow: 'hidden', ...softShadow },
  mentionRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 12, paddingVertical: 8 },
  mentionName: { fontSize: 15, color: t.text, fontWeight: '600' },
  replyBar: { flexDirection: 'row', alignItems: 'center', gap: 10, marginHorizontal: 10, marginBottom: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 14, overflow: 'hidden' },
  replyBarLine: { width: 3, alignSelf: 'stretch', borderRadius: 2, backgroundColor: t.gold },
  // composer
  composerHover: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  composer: { flexDirection: 'row', gap: 9, paddingHorizontal: 12, paddingVertical: 9, alignItems: 'flex-end' },
  iconCircle: { width: 42, height: 42, borderRadius: 21, borderWidth: 1, borderColor: t.line, alignItems: 'center', justifyContent: 'center' },
  capsule: { flex: 1, minHeight: 42, maxHeight: 120, borderRadius: 22, paddingHorizontal: 16, paddingTop: 11, paddingBottom: 11, fontSize: 16, backgroundColor: t.capsule, color: t.text },
  sendCircle: { width: 44, height: 44, borderRadius: 22, backgroundColor: t.gold, alignItems: 'center', justifyContent: 'center', ...softShadow, shadowColor: t.gold, shadowOpacity: 0.4 },
});

const LIGHT_STYLES = makeStyles(LIGHT);
const DARK_STYLES = makeStyles(DARK);
const ThemeCtx = createContext({ t: LIGHT, styles: LIGHT_STYLES });
const useTheme = () => useContext(ThemeCtx);

// ─────────────────────────── helpers ───────────────────────────
function useKeyboard() {
  const [kb, setKb] = useState({ open: false, height: 0 });
  useEffect(() => {
    const showEvt = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvt = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const s = Keyboard.addListener(showEvt, (e: any) => setKb({ open: true, height: e?.endCoordinates?.height || 0 }));
    const h = Keyboard.addListener(hideEvt, () => setKb({ open: false, height: 0 }));
    return () => { s.remove(); h.remove(); };
  }, []);
  return kb;
}
function formData(fields: Record<string, string>) {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
  return fd;
}
function initials(n?: string) {
  return (n || '?').trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase();
}
function when(iso?: string) {
  if (!iso) return '';
  const d = new Date(iso), n = new Date();
  const t = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  return d.toDateString() === n.toDateString()
    ? `сегодня ${t}`
    : `${d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })} ${t}`;
}
function dayLabel(iso?: string) {
  if (!iso) return '';
  const d = new Date(iso), n = new Date();
  if (d.toDateString() === n.toDateString()) return 'сегодня';
  const y = new Date(n); y.setDate(n.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return 'вчера';
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
}
// interleave day separators into a chronological message array (for inverted lists)
function withDays<T extends { created_at?: string }>(msgs: T[]): (T | { sep: string; id: string })[] {
  const out: any[] = [];
  let prev = '';
  msgs.forEach((m, i) => {
    const lbl = dayLabel(m.created_at);
    if (lbl && lbl !== prev) { out.push({ sep: lbl, id: `sep-${i}` }); prev = lbl; }
    out.push(m);
  });
  return out;
}
// camera-or-gallery chooser → returns the picked asset (photo or video) or null
async function pickMedia(): Promise<ImagePicker.ImagePickerAsset | null> {
  return new Promise((resolve) => {
    const open = async (camera: boolean) => {
      try {
        const perm = camera
          ? await ImagePicker.requestCameraPermissionsAsync()
          : await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!perm.granted) { resolve(null); return; }
        const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ['images', 'videos'], quality: 0.7, videoMaxDuration: 60 };
        const res = camera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
        if (res.canceled) { resolve(null); return; }
        resolve(res.assets[0]);   // upload starts immediately — gallery save must never block it
        if (camera) {             // fire-and-forget: camera shots also land in the phone's gallery
          setTimeout(() => {
            MediaLibrary.requestPermissionsAsync(true)
              .then((perm) => { if (perm.granted) return MediaLibrary.saveToLibraryAsync(res.assets[0].uri); })
              .catch(() => {});
          }, 600);
        }
      } catch { resolve(null); }
    };
    Alert.alert('Фото или видео', 'Снимок уйдёт в ленту — Flagleaf распознает и сохранит для обучения.', [
      { text: 'Камера', onPress: () => open(true) },
      { text: 'Галерея', onPress: () => open(false) },
      { text: 'Отмена', style: 'cancel', onPress: () => resolve(null) },
    ]);
  });
}
function Logo({ size = 20 }: { size?: number }) {
  const { t, styles } = useTheme();
  return <Text style={[styles.logo, { fontSize: size }]}><Text style={{ color: t.gold }}>E</Text>AR</Text>;
}

// ─────────────────────────── root ───────────────────────────
export default function App() {
  const scheme = useColorScheme();
  const themeVal = useMemo(
    () => (scheme === 'dark' ? { t: DARK, styles: DARK_STYLES } : { t: LIGHT, styles: LIGHT_STYLES }),
    [scheme]);
  const [ready, setReady] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  useEffect(() => {
    (async () => {
      const tok = await getToken();
      if (tok) { try { await api.get('/api/me'); setLoggedIn(true); } catch { await setToken(null); } }
      setReady(true);
    })();
  }, []);
  return (
    <ThemeCtx.Provider value={themeVal}>
      {!ready
        ? <View style={themeVal.styles.center}><ActivityIndicator color={themeVal.t.gold} /></View>
        : loggedIn
          ? <Main onLogout={async () => { await setToken(null); setLoggedIn(false); }} />
          : <Login onDone={() => setLoggedIn(true)} />}
    </ThemeCtx.Provider>
  );
}

// ─────────────────────────── login ───────────────────────────
function Login({ onDone }: { onDone: () => void }) {
  const { t, styles } = useTheme();
  const insets = useSafeAreaInsets();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const sendCode = async () => {
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { setNote('Введите корректный email.'); return; }
    setBusy(true); setNote('Отправляю код…');
    try { const r = await api.postJson('/api/auth/email/start', { email }); setNote(r?.message || 'Код отправлен на почту.'); }
    catch (e: any) { setNote(e?.message || 'Не удалось отправить код.'); } finally { setBusy(false); }
  };
  const verify = async () => {
    if (code.trim().length !== 6) { setNote('Введите 6 цифр кода.'); return; }
    setBusy(true); setNote('Проверяю…');
    try { const r = await api.postJson('/api/auth/verify', { code: code.trim() }); await setToken(r.token); onDone(); }
    catch (e: any) { setNote(e?.message || 'Не удалось войти.'); setBusy(false); }
  };
  return (
    <View style={[styles.screen, { paddingTop: insets.top + 40, paddingHorizontal: 24 }]}>
      <Logo size={22} />
      <Text style={styles.h1}>Вход для агрономов</Text>
      <Text style={styles.lead}>ИИ-агроном, скаутинг и лента команды — для зарегистрированных агрономов хозяйства.</Text>
      <Text style={styles.fld}>Почта</Text>
      <TextInput style={styles.input} value={email} onChangeText={setEmail} placeholder="email"
        autoCapitalize="none" keyboardType="email-address" placeholderTextColor={t.muted} />
      <Pressable style={[styles.btn, busy && styles.off]} onPress={sendCode} disabled={busy}><Text style={styles.btnTxt}>Отправить код на почту</Text></Pressable>
      <Text style={[styles.fld, { marginTop: 18 }]}>Код из письма</Text>
      <TextInput style={[styles.input, styles.code]} value={code} onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
        placeholder="——————" keyboardType="number-pad" maxLength={6} placeholderTextColor={t.muted} />
      <Pressable style={[styles.btn, busy && styles.off]} onPress={verify} disabled={busy}><Text style={styles.btnTxt}>Войти</Text></Pressable>
      {!!note && <Text style={styles.note}>{note}</Text>}
      <Text style={styles.help}>Нет почты в системе — получите код в Telegram-боте Flagleaf командой /weblogin.</Text>
    </View>
  );
}

// ─────────────────────────── logged-in shell ───────────────────────────
type Chat = { kind: 'feed' } | { kind: 'bot' } | { kind: 'person'; id: number; name: string };

function Main({ onLogout }: { onLogout: () => void }) {
  const { t, styles } = useTheme();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [me, setMe] = useState<any>(null);
  const [open, setOpen] = useState<null | Chat>(null);
  const slide = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    api.get('/api/me').then(setMe).catch(() => {});
    registerPush(); clearBadge();
    const sub = AppState.addEventListener('change', (s) => { if (s === 'active') clearBadge(); });
    return () => sub.remove();
  }, []);
  const headerPad = insets.top + 52;
  const openChat = (c: Chat) => {
    setOpen(c);
    Animated.timing(slide, { toValue: 1, duration: 240, useNativeDriver: true }).start();
  };
  const [listRefresh, setListRefresh] = useState(0);
  const back = () => {
    Keyboard.dismiss();
    Animated.timing(slide, { toValue: 0, duration: 210, useNativeDriver: true }).start(({ finished }) => {
      if (finished) { setOpen(null); setListRefresh((n) => n + 1); }   // returning home refreshes unread state
    });
  };
  // swipe from the left edge to go back (drag follows the finger, Telegram-style)
  const swipe = useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponder: (_e, g) =>
      g.dx > 12 && Math.abs(g.dx) > Math.abs(g.dy) * 1.5 && g.moveX - g.dx < 32,
    onPanResponderMove: (_e, g) => slide.setValue(1 - Math.min(Math.max(g.dx / width, 0), 1)),
    onPanResponderRelease: (_e, g) => {
      if (g.dx > width / 3 || g.vx > 0.6) {
        Keyboard.dismiss();
        Animated.timing(slide, { toValue: 0, duration: 160, useNativeDriver: true }).start(({ finished }) => { if (finished) setOpen(null); });
      } else {
        Animated.timing(slide, { toValue: 1, duration: 160, useNativeDriver: true }).start();
      }
    },
    onPanResponderTerminate: () => {
      Animated.timing(slide, { toValue: 1, duration: 160, useNativeDriver: true }).start();
    },
  }), [width, slide]);
  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <ChatList me={me} onLogout={onLogout} onOpen={openChat} headerPad={headerPad} insetsTop={insets.top} bottomInset={insets.bottom} refreshKey={listRefresh} />

      {open && (
        <Animated.View style={[StyleSheet.absoluteFill, { backgroundColor: t.bg, zIndex: 20, elevation: 20, transform: [{ translateX: slide.interpolate({ inputRange: [0, 1], outputRange: [width, 0] }) }] }]}>
          {open.kind === 'feed' && <WallView me={me} onLogout={onLogout} headerPad={headerPad} bottomInset={insets.bottom} />}
          {open.kind === 'bot' && <DmView headerPad={headerPad} bottomInset={insets.bottom} />}
          {open.kind === 'person' && <PersonView peer={open} headerPad={headerPad} bottomInset={insets.bottom} />}
          <View style={[styles.headerGlass, styles.chatHdrBg, { paddingTop: insets.top, position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10 }]}>
            <View style={styles.chatHdrRow}>
              <Pressable onPress={back} hitSlop={14} style={styles.backBtn}>
                <Ionicons name="chevron-back" size={28} color={t.gold} />
                <Text style={styles.backTxt}>Чаты</Text>
              </Pressable>
              <View style={{ flex: 1 }} />
              {/* Telegram-style: title + circular avatar as one cluster on the right */}
              <Text style={styles.chatHdrTitle} numberOfLines={1}>
                {open.kind === 'feed' ? 'Лента команды' : open.kind === 'bot' ? 'Flagleaf' : open.name}
              </Text>
              <View style={[styles.chatHdrAv, open.kind === 'bot' ? styles.avBot : styles.avGroup]}>
                {open.kind === 'feed' ? <Ionicons name="people" size={18} color="#fff" />
                  : open.kind === 'bot' ? <Ionicons name="leaf" size={18} color={t.gold} />
                  : <Text style={styles.avInitialsSm}>{initials(open.name)}</Text>}
              </View>
            </View>
          </View>
          <View {...swipe.panHandlers} style={[styles.edgeStrip, { top: headerPad }]} />
        </Animated.View>
      )}
    </View>
  );
}

// ─────────────────────── chat list (home) ───────────────────────
function ChatList({ me, onLogout, onOpen, headerPad, insetsTop, bottomInset, refreshKey }:
  { me: any; onLogout: () => void; onOpen: (t: Chat) => void; headerPad: number; insetsTop: number; bottomInset: number; refreshKey?: number }) {
  const { t, styles } = useTheme();
  const [wall, setWall] = useState<any>(null);
  const [peers, setPeers] = useState<any[]>([]);
  const load = useCallback(() => {
    api.get('/api/chats').then((d) => { setWall(d.wall || null); setPeers(d.peers || []); }).catch(() => {});
  }, []);
  useEffect(() => {
    load();
    const iv = setInterval(load, 15000);   // keep previews + unread badges fresh
    return () => clearInterval(iv);
  }, [load, refreshKey]);
  const feedPreview = wall
    ? `${wall.author || ''}: ${wall.body || '…'}`.trim()
    : 'Наблюдения команды, ответы ИИ, проверка старшим';
  return (
    <View style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={{ paddingTop: headerPad + 6, paddingBottom: bottomInset + 16 }}>
        <ChatRow onPress={() => onOpen({ kind: 'feed' })} avStyle={styles.avGroup}
          icon={<Ionicons name="people" size={24} color="#fff" />}
          title="Лента команды" pinned time={when(wall?.created_at)} preview={feedPreview}
          unread={wall?.unread} />
        <ChatRow onPress={() => onOpen({ kind: 'bot' })} avStyle={styles.avBot}
          icon={<Ionicons name="leaf" size={24} color={t.gold} />}
          title="Flagleaf · ИИ-агроном" preview="Личный чат: препараты, ЭПВ, история и план поля" />
        {peers.map((p) => (
          <ChatRow key={p.id} onPress={() => onOpen({ kind: 'person', id: p.id, name: p.name })}
            avStyle={styles.avPerson} icon={<Text style={styles.avInitials}>{initials(p.name)}</Text>}
            title={p.name} time={p.last_at ? when(p.last_at) : undefined}
            preview={p.last_body ? `${p.last_mine ? 'Вы: ' : ''}${p.last_body}` : (p.role === 'admin' ? 'руководитель' : 'агроном')}
            unread={p.unread} />
        ))}
        <Text style={styles.versionStamp}>{VERSION_STAMP}</Text>
      </ScrollView>

      <BlurView intensity={75} tint={t.blurTint} style={[styles.headerGlass, { paddingTop: insetsTop, position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10 }]}>
        <View style={styles.headerRow}>
          <Logo />
          <Text style={styles.hdrRight}>{me?.name || ''} · <Text style={{ color: t.gold }} onPress={onLogout}>выйти</Text></Text>
        </View>
      </BlurView>
    </View>
  );
}
function ChatRow({ onPress, icon, avStyle, title, preview, time, pinned, unread }:
  { onPress: () => void; icon: any; avStyle: any; title: string; preview: string; time?: string; pinned?: boolean; unread?: number }) {
  const { t, styles } = useTheme();
  const hot = !!unread;   // Telegram-style: unread chats read bold
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.chatRow, pressed && { backgroundColor: t.pressed }]}>
      <View style={[styles.rowAvLg, avStyle]}>{icon}</View>
      <View style={{ flex: 1 }}>
        <View style={styles.rowTop}>
          <Text style={styles.rowTitle} numberOfLines={1}>{title}</Text>
          {pinned && <Ionicons name="pin" size={13} color={t.muted} style={{ marginLeft: 5 }} />}
          <View style={{ flex: 1 }} />
          {!!time && <Text style={[styles.rowTime, hot && { color: t.gold, fontWeight: '700' }]}>{time}</Text>}
        </View>
        <View style={styles.rowTop}>
          <Text style={[styles.rowPreview, { flex: 1 }, hot && { color: t.text, fontWeight: '700' }]} numberOfLines={1}>{preview}</Text>
          {!!unread && <View style={styles.unreadBadge}><Text style={styles.unreadTxt}>{unread}</Text></View>}
        </View>
      </View>
    </Pressable>
  );
}

function Composer({ value, onChange, onSend, busy, placeholder, onCamera }:
  { value: string; onChange: (s: string) => void; onSend: () => void; busy: boolean; placeholder: string; onCamera?: () => void }) {
  const { t, styles } = useTheme();
  return (
    <BlurView intensity={70} tint={t.blurTint} style={styles.composer}>
      {onCamera && <Pressable style={styles.iconCircle} onPress={onCamera} disabled={busy}><Ionicons name="camera-outline" size={20} color={t.gold} /></Pressable>}
      <TextInput style={styles.capsule} value={value} onChangeText={onChange} placeholder={placeholder} placeholderTextColor={t.muted} multiline />
      <Pressable style={[styles.sendCircle, busy && styles.off]} onPress={onSend} disabled={busy}>
        {busy ? <ActivityIndicator color="#fff" size="small" /> : <Ionicons name="arrow-up" size={22} color="#fff" />}
      </Pressable>
    </BlurView>
  );
}

// ─────────────────────────── feed ───────────────────────────
function ImageZoom({ uri, onClose }: { uri: string | null; onClose: () => void }) {
  const { styles } = useTheme();
  return (
    <Modal visible={!!uri} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.viewerBg}>
        <ScrollView maximumZoomScale={5} minimumZoomScale={1} contentContainerStyle={styles.viewerScroll}
          centerContent showsVerticalScrollIndicator={false} showsHorizontalScrollIndicator={false}>
          {!!uri && <Image source={{ uri }} style={styles.viewerImg} resizeMode="contain" />}
        </ScrollView>
        <Pressable style={styles.viewerClose} onPress={onClose} hitSlop={14}>
          <Ionicons name="close" size={30} color="#fff" />
        </Pressable>
      </View>
    </Modal>
  );
}

// message text with @mentions highlighted
function MsgText({ body, style }: { body?: string; style?: any }) {
  const { t } = useTheme();
  if (!body) return null;
  const parts = body.split(/(@[^\s@,.:;!?]+)/g);
  return (
    <Text style={style}>
      {parts.map((p, i) => /^@/.test(p)
        ? <Text key={i} style={{ color: t.gold, fontWeight: '700' }}>{p}</Text>
        : <Text key={i}>{p}</Text>)}
    </Text>
  );
}

function ReplyQuote({ author, snippet }: { author?: string | null; snippet?: string | null }) {
  const { styles } = useTheme();
  return (
    <View style={styles.replyQuote}>
      <Text style={styles.replyQuoteAuthor} numberOfLines={1}>{author || ''}</Text>
      <Text style={styles.replyQuoteText} numberOfLines={1}>{snippet || ''}</Text>
    </View>
  );
}

// one wall message: bot panel, prominent media card, or chat bubble
function WallMsg({ m, mine, chief, onReply, onReact, onZoom }:
  { m: any; mine: boolean; chief: boolean; onReply: (m: any) => void; onReact: (id: number, v: string) => void; onZoom: (uri: string) => void }) {
  const { t, styles } = useTheme();
  const verdict = m.ups > 0 ? 'up' : m.downs > 0 ? 'down' : null;
  if (m.is_bot) {
    return (
      <Pressable onLongPress={() => onReply(m)} style={styles.botWrap}>
        {!!m.reply_to && <ReplyQuote author={m.reply_author} snippet={m.reply_snippet} />}
        <View style={styles.botLabel}><Ionicons name="leaf" size={14} color={t.botLabel} /><Text style={styles.botLabelTxt}> Flagleaf</Text></View>
        <MsgText body={m.body} style={styles.botTxt} />
        <Text style={styles.wallTime}>{when(m.created_at)}</Text>
      </Pressable>
    );
  }
  if (m.media) {
    return (
      <Pressable onLongPress={() => onReply(m)} style={styles.post}>
        <Text style={styles.pauth}>{m.author}{m.field ? <Text style={styles.pmeta}>  · {m.field}</Text> : null}</Text>
        {!!m.reply_to && <ReplyQuote author={m.reply_author} snippet={m.reply_snippet} />}
        {m.is_video
          ? <View style={styles.videoBox}><Ionicons name="videocam-outline" size={30} color={t.muted} /></View>
          : <Pressable onPress={() => onZoom(m.media)}><Image source={{ uri: m.media }} style={styles.pmedia} resizeMode="cover" /></Pressable>}
        {!!m.body && <MsgText body={m.body} style={styles.pbody} />}
        <View style={styles.actRow}>
          {verdict && (
            <View style={[styles.pill, verdict === 'up' ? styles.pillOk : styles.pillBad]}>
              <Ionicons name={verdict === 'up' ? 'checkmark' : 'close'} size={14} color={verdict === 'up' ? t.pillOk : t.pillBad} />
              <Text style={[styles.pillTxt, { color: verdict === 'up' ? t.pillOk : t.pillBad }]}>{verdict === 'up' ? 'подтвердил старший' : 'отклонил старший'}</Text>
            </View>
          )}
          {chief && (
            <View style={styles.verdictBtns}>
              <Pressable onPress={() => onReact(m.id, verdict === 'up' ? 'none' : 'up')} style={[styles.vBtn, verdict === 'up' && styles.vBtnOn]} hitSlop={6}><Ionicons name="checkmark" size={18} color={verdict === 'up' ? t.pillOk : t.muted} /></Pressable>
              <Pressable onPress={() => onReact(m.id, verdict === 'down' ? 'none' : 'down')} style={[styles.vBtn, verdict === 'down' && styles.vBtnOn]} hitSlop={6}><Ionicons name="close" size={18} color={verdict === 'down' ? t.pillBad : t.muted} /></Pressable>
            </View>
          )}
          <Text style={[styles.wallTime, { marginLeft: 'auto' }]}>{when(m.created_at)}</Text>
        </View>
      </Pressable>
    );
  }
  return (
    <Pressable onLongPress={() => onReply(m)} style={[styles.bubble, mine ? styles.bubbleUser : styles.bubbleBot]}>
      {!mine && <Text style={styles.wallAuthorSm}>{m.author}{chief && m.chief ? ' • старший' : ''}</Text>}
      {!!m.reply_to && <ReplyQuote author={m.reply_author} snippet={m.reply_snippet} />}
      <MsgText body={m.body} style={mine ? styles.bubbleUserTxt : styles.bubbleBotTxt} />
    </Pressable>
  );
}

// swipe a message left to reply (drag follows the finger, springs back; long-press still works)
function SwipeReply({ onReply, children }: { onReply: () => void; children: any }) {
  const { t } = useTheme();
  const tx = useRef(new Animated.Value(0)).current;
  const fired = useRef(false);
  const pan = useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponder: (_e, g) => g.dx < -12 && Math.abs(g.dx) > Math.abs(g.dy) * 1.6,
    onPanResponderGrant: () => { fired.current = false; },
    onPanResponderMove: (_e, g) => {
      const d = Math.max(g.dx, -82);
      tx.setValue(d);
      if (!fired.current && d <= -56) { fired.current = true; onReply(); }   // fire once at threshold
    },
    onPanResponderRelease: () => Animated.spring(tx, { toValue: 0, useNativeDriver: true, bounciness: 8 }).start(),
    onPanResponderTerminate: () => Animated.spring(tx, { toValue: 0, useNativeDriver: true }).start(),
  }), [onReply, tx]);
  const iconOpacity = tx.interpolate({ inputRange: [-56, -20, 0], outputRange: [1, 0.25, 0] });
  return (
    <View>
      <Animated.View style={{ position: 'absolute', right: 14, top: 0, bottom: 0, justifyContent: 'center', opacity: iconOpacity }}>
        <Ionicons name="arrow-undo" size={20} color={t.gold} />
      </Animated.View>
      <Animated.View style={{ transform: [{ translateX: tx }] }} {...pan.panHandlers}>{children}</Animated.View>
    </View>
  );
}

function WallView({ me, onLogout, headerPad, bottomInset }: { me: any; onLogout: () => void; headerPad: number; bottomInset: number }) {
  const { t, styles } = useTheme();
  const [msgs, setMsgs] = useState<any[]>([]);
  const [members, setMembers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [replyTo, setReplyTo] = useState<any>(null);
  const [mentionQ, setMentionQ] = useState<string | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);
  const [thinking, setThinking] = useState(false);
  const kb = useKeyboard();
  const chief = me?.role === 'chief_agronomist' || me?.role === 'admin';
  const load = useCallback(async () => {
    try {
      const d = await api.get('/api/wall');
      setMsgs(d.messages || []);
      if ((d.messages || [])[0]?.is_bot) setThinking(false);   // bot has replied (it's newest)
    } catch (e: any) { if (e?.status === 401) onLogout(); } finally { setLoading(false); }
  }, [onLogout]);
  useEffect(() => {
    load();
    const iv = setInterval(load, thinking ? 4000 : 8000);   // poll faster while awaiting the bot
    return () => clearInterval(iv);
  }, [load, thinking]);
  useEffect(() => { api.get('/api/members').then((d) => setMembers(d.members || [])).catch(() => {}); }, []);

  const post = async (fd: FormData, botExpected: boolean) => {
    if (replyTo) fd.append('reply_to', String(replyTo.id));
    setText(''); setReplyTo(null); setMentionQ(null); setBusy(true);
    try {
      await api.postForm('/api/wall', fd);
      if (botExpected) { setThinking(true); setTimeout(() => setThinking(false), 60000); }
      await load();
    } catch (e: any) { Alert.alert('Не отправилось', e?.message || 'Проверьте связь и попробуйте ещё раз.'); }
    finally { setBusy(false); }
  };
  const send = () => {
    const b = text.trim(); if (!b || busy) return;
    const botExpected = /@(flagleaf|флаглиф|флаглаф|flag)\b/i.test(b) || /^\s*(бот|bot)\b/i.test(b) || !!replyTo?.bot;
    post(formData({ body: b }), botExpected);
  };
  const capture = async () => {
    const a = await pickMedia(); if (!a) return;
    const fd = formData({ body: text.trim() });
    const isVideo = a.type === 'video';
    fd.append(isVideo ? 'video' : 'image', {
      uri: a.uri, name: a.fileName || (isVideo ? 'scout.mp4' : 'photo.jpg'),
      type: a.mimeType || (isVideo ? 'video/mp4' : 'image/jpeg'),
    } as any);
    post(fd, true);   // media always gets an auto reply
  };
  const react = async (id: number, verdict: string) => {
    try { await api.postJson(`/api/wall/${id}/react`, { verdict }); await load(); } catch {}
  };
  const startReply = (m: any) => setReplyTo({ id: m.id, author: m.is_bot ? 'Flagleaf' : m.author, snippet: m.body || (m.media ? '📷 фото' : ''), bot: m.is_bot });

  const onChangeText = (v: string) => {
    setText(v);
    const mm = v.match(/@([^\s@]*)$/);
    setMentionQ(mm ? mm[1].toLowerCase() : null);
  };
  const pickMention = (name: string) => {
    setText((v) => v.replace(/@([^\s@]*)$/, `@${name} `));
    setMentionQ(null);
  };
  const mentionList = mentionQ !== null
    ? [{ id: 'bot', first: 'Flagleaf' }, ...members].filter((x: any) => (x.first || '').toLowerCase().startsWith(mentionQ)).slice(0, 5)
    : [];

  return (
    <View style={{ flex: 1 }}>
      {loading ? <View style={styles.center}><ActivityIndicator color={t.gold} /></View> : (
        <FlatList
          data={(() => {
            const d = [...withDays([...msgs].reverse())].reverse();   // oldest→newest for day sep, then newest-first for inverted
            return thinking ? [{ thinking: true, id: '__thinking' }, ...d] : d;
          })()}
          inverted keyExtractor={(m: any) => m.thinking ? '__thinking' : m.sep ? m.id : String(m.id)} style={StyleSheet.absoluteFill}
          contentContainerStyle={{ paddingHorizontal: 12, paddingTop: kb.open ? kb.height + 60 : bottomInset + (replyTo ? 118 : 72), paddingBottom: headerPad + 4, gap: 7 }}
          keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive"
          renderItem={({ item }: any) => item.thinking
            ? <View style={styles.botWrap}><View style={styles.botLabel}><Ionicons name="leaf" size={14} color={t.botLabel} /><Text style={styles.botLabelTxt}> Flagleaf</Text></View><Text style={styles.botTxt}>смотрит и отвечает…</Text></View>
            : item.sep
              ? <Text style={styles.daySep}>{item.sep}</Text>
              : <SwipeReply onReply={() => startReply(item)}><WallMsg m={item} mine={item.author_id === me?.id} chief={chief} onReply={startReply} onReact={react} onZoom={setZoom} /></SwipeReply>}
          ListEmptyComponent={<Text style={styles.empty}>Пока пусто. Сфотографируйте растение или напишите наблюдение — увидит вся команда. «@flagleaf» — спросить ИИ.</Text>} />
      )}
      <ImageZoom uri={zoom} onClose={() => setZoom(null)} />
      <KeyboardAvoidingView style={styles.composerHover} behavior={Platform.OS === 'ios' ? 'padding' : undefined} pointerEvents="box-none">
        <View style={{ marginBottom: kb.open ? (Platform.OS === 'ios' ? 0 : kb.height + 52) : Math.max(bottomInset, 10) }}>
          {mentionList.length > 0 && (
            <View style={styles.mentionBox}>
              {mentionList.map((x: any) => (
                <Pressable key={String(x.id)} onPress={() => pickMention(x.first)} style={styles.mentionRow}>
                  <View style={[styles.rowAv, x.id === 'bot' ? styles.avBot : styles.avPerson]}>
                    {x.id === 'bot' ? <Ionicons name="leaf" size={15} color={t.gold} /> : <Text style={styles.avInitialsSm}>{initials(x.name)}</Text>}
                  </View>
                  <Text style={styles.mentionName}>{x.id === 'bot' ? 'Flagleaf' : x.name}</Text>
                </Pressable>
              ))}
            </View>
          )}
          {replyTo && (
            <BlurView intensity={60} tint={t.blurTint} style={styles.replyBar}>
              <View style={styles.replyBarLine} />
              <View style={{ flex: 1 }}>
                <Text style={styles.replyQuoteAuthor} numberOfLines={1}>{replyTo.author}</Text>
                <Text style={styles.replyQuoteText} numberOfLines={1}>{replyTo.snippet}</Text>
              </View>
              <Pressable onPress={() => setReplyTo(null)} hitSlop={10}><Ionicons name="close" size={20} color={t.muted} /></Pressable>
            </BlurView>
          )}
          <Composer value={text} onChange={onChangeText} onSend={send} busy={busy} onCamera={capture} placeholder="Сообщение (@flagleaf — ИИ)" />
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

// ─────────────────────────── DM (you↔bot) ───────────────────────────
const BOT_GREETING = { role: 'bot' as const, text: 'Здравствуйте! Я ИИ-агроном Flagleaf. Здесь мы говорим лично — спросите про препараты, ЭПВ, историю или план поля.' };

function DmView({ headerPad, bottomInset }: { headerPad: number; bottomInset: number }) {
  const { t, styles } = useTheme();
  const [msgs, setMsgs] = useState<{ role: 'user' | 'bot'; text: string; created_at?: string }[]>([BOT_GREETING]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const kb = useKeyboard();
  useEffect(() => {   // history is server-side: survives restarts, follows the account across devices
    api.get('/api/chat/history')
      .then((d) => { if (d.messages?.length) setMsgs([BOT_GREETING, ...d.messages]); })
      .catch(() => {});
  }, []);
  const send = async () => {
    const q = text.trim(); if (!q || busy) return; setText('');
    const hist = msgs.slice(-6).map((m) => ({ role: m.role, text: m.text }));
    setMsgs((m) => [...m, { role: 'user', text: q }, { role: 'bot', text: '…' }]);
    setBusy(true);
    try {
      const r = await api.postJson('/api/chat', { question: q, history: hist });
      setMsgs((m) => { const cc = [...m]; cc[cc.length - 1] = { role: 'bot', text: r?.answer || 'Не понял вопрос — переформулируйте.' }; return cc; });
    } catch {
      setMsgs((m) => { const cc = [...m]; cc[cc.length - 1] = { role: 'bot', text: 'Ошибка сети. Попробуйте ещё раз.' }; return cc; });
    } finally { setBusy(false); }
  };
  return (
    <View style={{ flex: 1 }}>
      <FlatList data={[...withDays(msgs)].reverse()} inverted keyExtractor={(m: any, i) => m.sep ? m.id : String(i)} style={StyleSheet.absoluteFill}
        contentContainerStyle={{ paddingHorizontal: 14, paddingTop: kb.open ? kb.height + 64 : bottomInset + 72, paddingBottom: headerPad + 4, gap: 8 }} keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive"
        renderItem={({ item }: any) => item.sep
          ? <Text style={styles.daySep}>{item.sep}</Text>
          : (
          <View style={[styles.bubble, item.role === 'user' ? styles.bubbleUser : styles.bubbleBot]}>
            <Text style={item.role === 'user' ? styles.bubbleUserTxt : styles.bubbleBotTxt}>{item.text}</Text>
          </View>
        )} />
      <KeyboardAvoidingView style={styles.composerHover} behavior={Platform.OS === 'ios' ? 'padding' : undefined} pointerEvents="box-none">
        <View style={{ marginBottom: kb.open ? (Platform.OS === 'ios' ? 0 : kb.height + 52) : Math.max(bottomInset, 10) }}>
          <Composer value={text} onChange={setText} onSend={send} busy={busy} placeholder="Ваш вопрос агроному…" />
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

// ─────────────────── person DM (agronomist ↔ agronomist) ───────────────────
function PersonView({ peer, headerPad, bottomInset }: { peer: { id: number; name: string }; headerPad: number; bottomInset: number }) {
  const { t, styles } = useTheme();
  const [msgs, setMsgs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const kb = useKeyboard();
  const load = useCallback(async () => {
    try { const d = await api.get(`/api/dm/with/${peer.id}`); setMsgs(d.messages || []); }
    catch {} finally { setLoading(false); }
  }, [peer.id]);
  useEffect(() => {
    load();
    const iv = setInterval(load, 6000);    // near-live: poll the thread while it's open
    return () => clearInterval(iv);
  }, [load]);
  const send = async () => {
    const b = text.trim(); if (!b || busy) return; setText(''); setBusy(true);
    setMsgs((m) => [...m, { id: `tmp-${m.length}`, mine: true, body: b }]);
    try { await api.postJson(`/api/dm/with/${peer.id}`, { body: b }); await load(); }
    catch {} finally { setBusy(false); }
  };
  return (
    <View style={{ flex: 1 }}>
      {loading ? <View style={styles.center}><ActivityIndicator color={t.gold} /></View> : (
        <FlatList data={[...withDays(msgs)].reverse()} inverted keyExtractor={(m: any) => String(m.id)} style={StyleSheet.absoluteFill}
          contentContainerStyle={{ paddingHorizontal: 14, paddingTop: kb.open ? kb.height + 64 : bottomInset + 72, paddingBottom: headerPad + 4, gap: 8 }} keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive"
          renderItem={({ item }: any) => item.sep
            ? <Text style={styles.daySep}>{item.sep}</Text>
            : (
            <View style={[styles.bubble, item.mine ? styles.bubbleUser : styles.bubbleBot]}>
              <Text style={item.mine ? styles.bubbleUserTxt : styles.bubbleBotTxt}>{item.body}</Text>
              <View style={styles.bubbleMeta}>
                {!!item.created_at && <Text style={[styles.bubbleTime, item.mine && { color: t.dark ? 'rgba(244,236,217,0.55)' : 'rgba(255,255,255,0.55)' }]}>{when(item.created_at).replace('сегодня ', '')}</Text>}
                {item.mine && !String(item.id).startsWith('tmp') && (() => {
                  const faded = t.dark ? 'rgba(244,236,217,0.55)' : 'rgba(255,255,255,0.55)';
                  const [icon, color] = item.read
                    ? ['checkmark-done', t.gold]
                    : item.delivered
                      ? ['checkmark-done', faded]
                      : ['checkmark', faded];
                  return <Ionicons name={icon as any} size={13} color={color as string} />;
                })()}
              </View>
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>Личная переписка с {peer.name}. Видите только вы двое.</Text>} />
      )}
      <KeyboardAvoidingView style={styles.composerHover} behavior={Platform.OS === 'ios' ? 'padding' : undefined} pointerEvents="box-none">
        <View style={{ marginBottom: kb.open ? (Platform.OS === 'ios' ? 0 : kb.height + 52) : Math.max(bottomInset, 10) }}>
          <Composer value={text} onChange={setText} onSend={send} busy={busy} placeholder="Сообщение…" />
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}
