import { createContext, useContext, useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  ActivityIndicator, Animated, FlatList, Image, Keyboard, KeyboardAvoidingView, PanResponder,
  Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, useColorScheme, useWindowDimensions, View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BlurView } from 'expo-blur';
import { Ionicons } from '@expo/vector-icons';

import { api, getToken, setToken } from '@/lib/api';

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
  bubbleTime: { fontSize: 10.5, color: t.muted, marginTop: 3, alignSelf: 'flex-end' },
  rowTop: { flexDirection: 'row', alignItems: 'center' },
  rowTitle: { fontSize: 16.5, fontFamily: BRAND_FONT, fontWeight: '800', color: t.text, flexShrink: 1 },
  rowTime: { fontSize: 12, color: t.muted },
  rowPreview: { fontSize: 14, color: t.muted, marginTop: 3 },
  // chat header (inside an open conversation)
  chatHdrBg: { backgroundColor: t.headerBg },
  chatHdrRow: { flexDirection: 'row', alignItems: 'center', paddingLeft: 4, paddingRight: 16, paddingVertical: 9, gap: 8 },
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
  useEffect(() => { api.get('/api/me').then(setMe).catch(() => {}); }, []);
  const headerPad = insets.top + 52;
  const openChat = (c: Chat) => {
    setOpen(c);
    Animated.timing(slide, { toValue: 1, duration: 240, useNativeDriver: true }).start();
  };
  const back = () => {
    Keyboard.dismiss();
    Animated.timing(slide, { toValue: 0, duration: 210, useNativeDriver: true }).start(({ finished }) => { if (finished) setOpen(null); });
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
      <ChatList me={me} onLogout={onLogout} onOpen={openChat} headerPad={headerPad} insetsTop={insets.top} bottomInset={insets.bottom} />

      {open && (
        <Animated.View style={[StyleSheet.absoluteFill, { backgroundColor: t.bg, zIndex: 20, elevation: 20, transform: [{ translateX: slide.interpolate({ inputRange: [0, 1], outputRange: [width, 0] }) }] }]}>
          {open.kind === 'feed' && <FeedView onLogout={onLogout} headerPad={headerPad} bottomInset={insets.bottom} />}
          {open.kind === 'bot' && <DmView headerPad={headerPad} bottomInset={insets.bottom} />}
          {open.kind === 'person' && <PersonView peer={open} headerPad={headerPad} bottomInset={insets.bottom} />}
          <View style={[styles.headerGlass, styles.chatHdrBg, { paddingTop: insets.top, position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10 }]}>
            <View style={styles.chatHdrRow}>
              <Pressable onPress={back} hitSlop={14} style={styles.backBtn}>
                <Ionicons name="chevron-back" size={28} color={t.gold} />
                <Text style={styles.backTxt}>Чаты</Text>
              </Pressable>
              <View style={[styles.rowAv, open.kind === 'bot' ? styles.avBot : styles.avGroup]}>
                {open.kind === 'feed' ? <Ionicons name="people" size={17} color="#fff" />
                  : open.kind === 'bot' ? <Ionicons name="leaf" size={17} color={t.gold} />
                  : <Text style={styles.avInitialsSm}>{initials(open.name)}</Text>}
              </View>
              <Text style={styles.chatHdrTitle} numberOfLines={1}>
                {open.kind === 'feed' ? 'Лента команды' : open.kind === 'bot' ? 'Flagleaf · ИИ-агроном' : open.name}
              </Text>
            </View>
          </View>
          <View {...swipe.panHandlers} style={[styles.edgeStrip, { top: headerPad }]} />
        </Animated.View>
      )}
    </View>
  );
}

// ─────────────────────── chat list (home) ───────────────────────
function ChatList({ me, onLogout, onOpen, headerPad, insetsTop, bottomInset }:
  { me: any; onLogout: () => void; onOpen: (t: Chat) => void; headerPad: number; insetsTop: number; bottomInset: number }) {
  const { t, styles } = useTheme();
  const [last, setLast] = useState<any>(null);
  const [peers, setPeers] = useState<any[]>([]);
  const load = useCallback(() => {
    api.get('/api/feed').then((d) => setLast((d.posts || [])[0] || null)).catch(() => {});
    api.get('/api/dm/threads').then((d) => setPeers(d.peers || [])).catch(() => {});
  }, []);
  useEffect(() => {
    load();
    const iv = setInterval(load, 20000);   // keep previews + unread badges fresh
    return () => clearInterval(iv);
  }, [load]);
  const feedPreview = last
    ? `${last.author || ''}: ${last.body || (last.is_video ? '🎥 видео' : last.media ? '📷 фото' : '…')}`.trim()
    : 'Наблюдения команды, ответы ИИ, проверка старшим';
  return (
    <View style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={{ paddingTop: headerPad + 6, paddingBottom: bottomInset + 16 }}>
        <ChatRow onPress={() => onOpen({ kind: 'feed' })} avStyle={styles.avGroup}
          icon={<Ionicons name="people" size={24} color="#fff" />}
          title="Лента команды" pinned time={when(last?.created_at)} preview={feedPreview} />
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
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.chatRow, pressed && { backgroundColor: t.pressed }]}>
      <View style={[styles.rowAvLg, avStyle]}>{icon}</View>
      <View style={{ flex: 1 }}>
        <View style={styles.rowTop}>
          <Text style={styles.rowTitle} numberOfLines={1}>{title}</Text>
          {pinned && <Ionicons name="pin" size={13} color={t.muted} style={{ marginLeft: 5 }} />}
          <View style={{ flex: 1 }} />
          {!!time && <Text style={styles.rowTime}>{time}</Text>}
        </View>
        <View style={styles.rowTop}>
          <Text style={[styles.rowPreview, { flex: 1 }]} numberOfLines={1}>{preview}</Text>
          {!!unread && <View style={styles.unreadBadge}><Text style={styles.unreadTxt}>{unread}</Text></View>}
        </View>
      </View>
    </Pressable>
  );
}

function Composer({ value, onChange, onSend, busy, placeholder, camera }:
  { value: string; onChange: (s: string) => void; onSend: () => void; busy: boolean; placeholder: string; camera?: boolean }) {
  const { t, styles } = useTheme();
  return (
    <BlurView intensity={70} tint={t.blurTint} style={styles.composer}>
      {camera && <Pressable style={styles.iconCircle}><Ionicons name="camera-outline" size={20} color={t.gold} /></Pressable>}
      <TextInput style={styles.capsule} value={value} onChangeText={onChange} placeholder={placeholder} placeholderTextColor={t.muted} multiline />
      <Pressable style={[styles.sendCircle, busy && styles.off]} onPress={onSend} disabled={busy}>
        <Ionicons name="arrow-up" size={22} color="#fff" />
      </Pressable>
    </BlurView>
  );
}

// ─────────────────────────── feed ───────────────────────────
function FeedView({ onLogout, headerPad, bottomInset }: { onLogout: () => void; headerPad: number; bottomInset: number }) {
  const { t, styles } = useTheme();
  const [posts, setPosts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const kb = useKeyboard();
  const load = useCallback(async () => {
    try { const d = await api.get('/api/feed'); setPosts(d.posts || []); }
    catch (e: any) { if (e?.status === 401) onLogout(); } finally { setLoading(false); }
  }, [onLogout]);
  useEffect(() => { load(); }, [load]);
  const publish = async () => {
    const b = text.trim(); if (!b) return; setText(''); setBusy(true);
    try { await api.postForm('/api/feed/post', formData({ body: b })); await load(); } catch {} finally { setBusy(false); }
  };
  return (
    <View style={{ flex: 1 }}>
      {loading ? <View style={styles.center}><ActivityIndicator color={t.gold} /></View> : (
        <FlatList data={posts} inverted keyExtractor={(p) => String(p.id)} style={StyleSheet.absoluteFill}
          contentContainerStyle={{ paddingHorizontal: 14, paddingTop: kb.open ? kb.height + 64 : bottomInset + 72, paddingBottom: headerPad + 4, gap: 14 }} keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => <PostCard p={item} onChanged={load} />}
          ListEmptyComponent={<View style={styles.flip}><Text style={styles.empty}>Пока пусто. Напишите наблюдение — оно появится здесь для всей команды.</Text></View>} />
      )}
      <KeyboardAvoidingView style={styles.composerHover} behavior={Platform.OS === 'ios' ? 'padding' : undefined} pointerEvents="box-none">
        <View style={{ marginBottom: kb.open ? 0 : Math.max(bottomInset, 10) }}>
          <Composer value={text} onChange={setText} onSend={publish} busy={busy} camera placeholder="Сообщение команде…" />
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

function PostCard({ p, onChanged }: { p: any; onChanged: () => void }) {
  const { t, styles } = useTheme();
  const [c, setC] = useState('');
  const [sending, setSending] = useState(false);
  const addComment = async () => {
    const b = c.trim(); if (!b) return; setC(''); setSending(true);
    try { await api.postJson(`/api/feed/${p.id}/comment`, { body: b }); onChanged(); } catch {} finally { setSending(false); }
  };
  return (
    <View style={styles.post}>
      <View style={styles.phead}>
        <View style={styles.pav}><Text style={styles.pavTxt}>{initials(p.author)}</Text></View>
        <View style={{ flex: 1 }}>
          <Text style={styles.pauth}>{p.author}</Text>
          {(!!p.field || !!p.created_at) && (
            <Text style={styles.pmeta}>{p.field ? <><Ionicons name="location-outline" size={12} color={t.muted} /> {p.field} · </> : ''}{when(p.created_at)}</Text>
          )}
        </View>
      </View>
      {!!p.body && <Text style={styles.pbody}>{p.body}</Text>}
      {!!p.media && (p.is_video
        ? <View style={styles.videoBox}><Ionicons name="videocam-outline" size={30} color={t.muted} /></View>
        : <Image source={{ uri: p.media }} style={styles.pmedia} resizeMode="cover" />)}
      {(p.thread || []).filter((cm: any) => cm.is_bot).slice(0, 1).map((cm: any) => (
        <View key={cm.id} style={styles.botPanel}>
          <View style={styles.botLabel}><Ionicons name="leaf" size={14} color={t.botLabel} /><Text style={styles.botLabelTxt}> Flagleaf</Text></View>
          <Text style={styles.botTxt}>{cm.body}</Text>
        </View>
      ))}
      <View style={styles.actRow}>
        {(p.ups > 0 || p.downs > 0) && (
          <View style={[styles.pill, p.ups > 0 ? styles.pillOk : styles.pillBad]}>
            <Ionicons name={p.ups > 0 ? 'checkmark' : 'close'} size={14} color={p.ups > 0 ? t.pillOk : t.pillBad} />
            <Text style={[styles.pillTxt, { color: p.ups > 0 ? t.pillOk : t.pillBad }]}>{p.ups > 0 ? 'подтвердил старший' : 'отклонил старший'}</Text>
          </View>
        )}
        {(p.comments > 0) && <View style={styles.cmtCount}><Ionicons name="chatbubble-outline" size={14} color={t.muted} /><Text style={styles.cmtCountTxt}> {p.comments}</Text></View>}
      </View>
      {(p.thread || []).filter((cm: any) => !cm.is_bot).map((cm: any) => (
        <View key={cm.id} style={styles.cmt}>
          <Text style={styles.cb}><Text style={styles.ca}>{cm.author}{cm.chief ? ' • старший' : ''}</Text>  {cm.body}</Text>
        </View>
      ))}
      <View style={styles.cmtForm}>
        <TextInput style={styles.cinputSm} value={c} onChangeText={setC} placeholder="Ответить… («бот …» — спросить ИИ)" placeholderTextColor={t.muted} />
        <Pressable style={[styles.sendSm, sending && styles.off]} onPress={addComment} disabled={sending}><Ionicons name="arrow-up" size={18} color="#fff" /></Pressable>
      </View>
    </View>
  );
}

// ─────────────────────────── DM (you↔bot) ───────────────────────────
function DmView({ headerPad, bottomInset }: { headerPad: number; bottomInset: number }) {
  const { t, styles } = useTheme();
  const [msgs, setMsgs] = useState<{ role: 'user' | 'bot'; text: string }[]>([
    { role: 'bot', text: 'Здравствуйте! Я ИИ-агроном Flagleaf. Здесь мы говорим лично — спросите про препараты, ЭПВ, историю или план поля.' },
  ]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const kb = useKeyboard();
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
      <FlatList data={[...msgs].reverse()} inverted keyExtractor={(_, i) => String(i)} style={StyleSheet.absoluteFill}
        contentContainerStyle={{ paddingHorizontal: 14, paddingTop: kb.open ? kb.height + 64 : bottomInset + 72, paddingBottom: headerPad + 4, gap: 8 }} keyboardShouldPersistTaps="handled"
        renderItem={({ item }) => (
          <View style={[styles.bubble, item.role === 'user' ? styles.bubbleUser : styles.bubbleBot]}>
            <Text style={item.role === 'user' ? styles.bubbleUserTxt : styles.bubbleBotTxt}>{item.text}</Text>
          </View>
        )} />
      <KeyboardAvoidingView style={styles.composerHover} behavior={Platform.OS === 'ios' ? 'padding' : undefined} pointerEvents="box-none">
        <View style={{ marginBottom: kb.open ? 0 : Math.max(bottomInset, 10) }}>
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
        <FlatList data={[...msgs].reverse()} inverted keyExtractor={(m) => String(m.id)} style={StyleSheet.absoluteFill}
          contentContainerStyle={{ paddingHorizontal: 14, paddingTop: kb.open ? kb.height + 64 : bottomInset + 72, paddingBottom: headerPad + 4, gap: 8 }} keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => (
            <View style={[styles.bubble, item.mine ? styles.bubbleUser : styles.bubbleBot]}>
              <Text style={item.mine ? styles.bubbleUserTxt : styles.bubbleBotTxt}>{item.body}</Text>
              {!!item.created_at && <Text style={[styles.bubbleTime, item.mine && { color: t.dark ? 'rgba(244,236,217,0.55)' : 'rgba(255,255,255,0.55)' }]}>{when(item.created_at)}</Text>}
            </View>
          )}
          ListEmptyComponent={<View style={styles.flip}><Text style={styles.empty}>Личная переписка с {peer.name}. Видите только вы двое.</Text></View>} />
      )}
      <KeyboardAvoidingView style={styles.composerHover} behavior={Platform.OS === 'ios' ? 'padding' : undefined} pointerEvents="box-none">
        <View style={{ marginBottom: kb.open ? 0 : Math.max(bottomInset, 10) }}>
          <Composer value={text} onChange={setText} onSend={send} busy={busy} placeholder="Сообщение…" />
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}
