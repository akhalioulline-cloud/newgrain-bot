import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  ActivityIndicator, Animated, FlatList, Image, Keyboard, KeyboardAvoidingView, PanResponder,
  Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, useWindowDimensions, View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BlurView } from 'expo-blur';
import { Ionicons } from '@expo/vector-icons';

import { api, getToken, setToken } from '@/lib/api';

const GOLD = '#b9994b', INK = '#1a1a1a', BG = '#faf7f1', LINE = '#e7e2d8', MUTED = '#9a8f7a';
// dense rounded brand face; system-bundled on iOS, Roboto Black on Android — no font assets needed
const BRAND_FONT = Platform.select({ ios: 'Avenir Next', android: 'sans-serif-black', default: undefined });
const softShadow = {
  shadowColor: '#3c280a', shadowOpacity: 0.08, shadowRadius: 16, shadowOffset: { width: 0, height: 6 }, elevation: 3,
};

function useKeyboardOpen() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const showEvt = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvt = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const s = Keyboard.addListener(showEvt, () => setOpen(true));
    const h = Keyboard.addListener(hideEvt, () => setOpen(false));
    return () => { s.remove(); h.remove(); };
  }, []);
  return open;
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
  return <Text style={[styles.logo, { fontSize: size }]}><Text style={{ color: GOLD }}>E</Text>AR</Text>;
}

// ─────────────────────────── root ───────────────────────────
export default function App() {
  const [ready, setReady] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  useEffect(() => {
    (async () => {
      const tok = await getToken();
      if (tok) { try { await api.get('/api/me'); setLoggedIn(true); } catch { await setToken(null); } }
      setReady(true);
    })();
  }, []);
  if (!ready) return <View style={styles.center}><ActivityIndicator color={GOLD} /></View>;
  return loggedIn
    ? <Main onLogout={async () => { await setToken(null); setLoggedIn(false); }} />
    : <Login onDone={() => setLoggedIn(true)} />;
}

// ─────────────────────────── login ───────────────────────────
function Login({ onDone }: { onDone: () => void }) {
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
        autoCapitalize="none" keyboardType="email-address" placeholderTextColor={MUTED} />
      <Pressable style={[styles.btn, busy && styles.off]} onPress={sendCode} disabled={busy}><Text style={styles.btnTxt}>Отправить код на почту</Text></Pressable>
      <Text style={[styles.fld, { marginTop: 18 }]}>Код из письма</Text>
      <TextInput style={[styles.input, styles.code]} value={code} onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
        placeholder="——————" keyboardType="number-pad" maxLength={6} placeholderTextColor={MUTED} />
      <Pressable style={[styles.btn, busy && styles.off]} onPress={verify} disabled={busy}><Text style={styles.btnTxt}>Войти</Text></Pressable>
      {!!note && <Text style={styles.note}>{note}</Text>}
      <Text style={styles.help}>Нет почты в системе — получите код в Telegram-боте Flagleaf командой /weblogin.</Text>
    </View>
  );
}

// ─────────────────────────── logged-in shell ───────────────────────────
type Chat = { kind: 'feed' } | { kind: 'bot' } | { kind: 'person'; id: number; name: string };

function Main({ onLogout }: { onLogout: () => void }) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [me, setMe] = useState<any>(null);
  const [open, setOpen] = useState<null | Chat>(null);
  const slide = useRef(new Animated.Value(0)).current;
  useEffect(() => { api.get('/api/me').then(setMe).catch(() => {}); }, []);
  const headerPad = insets.top + 52;
  const openChat = (t: Chat) => {
    setOpen(t);
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
    <View style={{ flex: 1, backgroundColor: BG }}>
      <ChatList me={me} onLogout={onLogout} onOpen={openChat} headerPad={headerPad} insetsTop={insets.top} bottomInset={insets.bottom} />

      {open && (
        <Animated.View style={[StyleSheet.absoluteFill, { backgroundColor: BG, zIndex: 20, elevation: 20, transform: [{ translateX: slide.interpolate({ inputRange: [0, 1], outputRange: [width, 0] }) }] }]}>
          {open.kind === 'feed' && <FeedView onLogout={onLogout} headerPad={headerPad} bottomInset={insets.bottom} />}
          {open.kind === 'bot' && <DmView headerPad={headerPad} bottomInset={insets.bottom} />}
          {open.kind === 'person' && <PersonView peer={open} headerPad={headerPad} bottomInset={insets.bottom} />}
          <View style={[styles.headerGlass, styles.chatHdrBg, { paddingTop: insets.top, position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10 }]}>
            <View style={styles.chatHdrRow}>
              <Pressable onPress={back} hitSlop={14} style={styles.backBtn}>
                <Ionicons name="chevron-back" size={28} color={GOLD} />
                <Text style={styles.backTxt}>Чаты</Text>
              </Pressable>
              <View style={[styles.rowAv, open.kind === 'bot' ? styles.avBot : styles.avGroup]}>
                {open.kind === 'feed' ? <Ionicons name="people" size={17} color="#fff" />
                  : open.kind === 'bot' ? <Ionicons name="leaf" size={17} color={GOLD} />
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
  const [last, setLast] = useState<any>(null);
  const [peers, setPeers] = useState<any[]>([]);
  const load = useCallback(() => {
    api.get('/api/feed').then((d) => setLast((d.posts || [])[0] || null)).catch(() => {});
    api.get('/api/dm/threads').then((d) => setPeers(d.peers || [])).catch(() => {});
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 20000);   // keep previews + unread badges fresh
    return () => clearInterval(t);
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
          icon={<Ionicons name="leaf" size={24} color={GOLD} />}
          title="Flagleaf · ИИ-агроном" preview="Личный чат: препараты, ЭПВ, история и план поля" />
        {peers.map((p) => (
          <ChatRow key={p.id} onPress={() => onOpen({ kind: 'person', id: p.id, name: p.name })}
            avStyle={styles.avPerson} icon={<Text style={styles.avInitials}>{initials(p.name)}</Text>}
            title={p.name} time={p.last_at ? when(p.last_at) : undefined}
            preview={p.last_body ? `${p.last_mine ? 'Вы: ' : ''}${p.last_body}` : (p.role === 'admin' ? 'руководитель' : 'агроном')}
            unread={p.unread} />
        ))}
      </ScrollView>

      <BlurView intensity={75} tint="light" style={[styles.headerGlass, { paddingTop: insetsTop, position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10 }]}>
        <View style={styles.headerRow}>
          <Logo />
          <Text style={styles.hdrRight}>{me?.name || ''} · <Text style={{ color: GOLD }} onPress={onLogout}>выйти</Text></Text>
        </View>
      </BlurView>
    </View>
  );
}
function ChatRow({ onPress, icon, avStyle, title, preview, time, pinned, unread }:
  { onPress: () => void; icon: any; avStyle: any; title: string; preview: string; time?: string; pinned?: boolean; unread?: number }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.chatRow, pressed && { backgroundColor: 'rgba(120,90,30,0.05)' }]}>
      <View style={[styles.rowAvLg, avStyle]}>{icon}</View>
      <View style={{ flex: 1 }}>
        <View style={styles.rowTop}>
          <Text style={styles.rowTitle} numberOfLines={1}>{title}</Text>
          {pinned && <Ionicons name="pin" size={13} color={MUTED} style={{ marginLeft: 5 }} />}
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
  return (
    <BlurView intensity={70} tint="light" style={styles.composer}>
      {camera && <Pressable style={styles.iconCircle}><Ionicons name="camera-outline" size={20} color={GOLD} /></Pressable>}
      <TextInput style={styles.capsule} value={value} onChangeText={onChange} placeholder={placeholder} placeholderTextColor={MUTED} multiline />
      <Pressable style={[styles.sendCircle, busy && styles.off]} onPress={onSend} disabled={busy}>
        <Ionicons name="arrow-up" size={22} color="#fff" />
      </Pressable>
    </BlurView>
  );
}

// ─────────────────────────── feed ───────────────────────────
function FeedView({ onLogout, headerPad, bottomInset }: { onLogout: () => void; headerPad: number; bottomInset: number }) {
  const [posts, setPosts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const kbOpen = useKeyboardOpen();
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
      {loading ? <View style={styles.center}><ActivityIndicator color={GOLD} /></View> : (
        <FlatList data={posts} inverted keyExtractor={(p) => String(p.id)} style={StyleSheet.absoluteFill}
          contentContainerStyle={{ paddingHorizontal: 14, paddingTop: bottomInset + 72, paddingBottom: headerPad + 4, gap: 14 }} keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => <PostCard p={item} onChanged={load} />}
          ListEmptyComponent={<View style={styles.flip}><Text style={styles.empty}>Пока пусто. Напишите наблюдение — оно появится здесь для всей команды.</Text></View>} />
      )}
      <KeyboardAvoidingView style={styles.composerHover} behavior={Platform.OS === 'ios' ? 'padding' : undefined} pointerEvents="box-none">
        <View style={{ marginBottom: kbOpen ? 0 : Math.max(bottomInset, 10) }}>
          <Composer value={text} onChange={setText} onSend={publish} busy={busy} camera placeholder="Сообщение команде…" />
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

function PostCard({ p, onChanged }: { p: any; onChanged: () => void }) {
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
            <Text style={styles.pmeta}>{p.field ? <><Ionicons name="location-outline" size={12} color={MUTED} /> {p.field} · </> : ''}{when(p.created_at)}</Text>
          )}
        </View>
      </View>
      {!!p.body && <Text style={styles.pbody}>{p.body}</Text>}
      {!!p.media && (p.is_video
        ? <View style={styles.videoBox}><Ionicons name="videocam-outline" size={30} color={MUTED} /></View>
        : <Image source={{ uri: p.media }} style={styles.pmedia} resizeMode="cover" />)}
      {(p.thread || []).filter((cm: any) => cm.is_bot).slice(0, 1).map((cm: any) => (
        <View key={cm.id} style={styles.botPanel}>
          <View style={styles.botLabel}><Ionicons name="leaf" size={14} color="#9a7b1e" /><Text style={styles.botLabelTxt}> Flagleaf</Text></View>
          <Text style={styles.botTxt}>{cm.body}</Text>
        </View>
      ))}
      <View style={styles.actRow}>
        {(p.ups > 0 || p.downs > 0) && (
          <View style={[styles.pill, p.ups > 0 ? styles.pillOk : styles.pillBad]}>
            <Ionicons name={p.ups > 0 ? 'checkmark' : 'close'} size={14} color={p.ups > 0 ? '#3b6d11' : '#a32d2d'} />
            <Text style={[styles.pillTxt, { color: p.ups > 0 ? '#3b6d11' : '#a32d2d' }]}>{p.ups > 0 ? 'подтвердил старший' : 'отклонил старший'}</Text>
          </View>
        )}
        {(p.comments > 0) && <View style={styles.cmtCount}><Ionicons name="chatbubble-outline" size={14} color={MUTED} /><Text style={styles.cmtCountTxt}> {p.comments}</Text></View>}
      </View>
      {(p.thread || []).filter((cm: any) => !cm.is_bot).map((cm: any) => (
        <View key={cm.id} style={styles.cmt}>
          <Text style={styles.cb}><Text style={styles.ca}>{cm.author}{cm.chief ? ' • старший' : ''}</Text>  {cm.body}</Text>
        </View>
      ))}
      <View style={styles.cmtForm}>
        <TextInput style={styles.cinputSm} value={c} onChangeText={setC} placeholder="Ответить… («бот …» — спросить ИИ)" placeholderTextColor={MUTED} />
        <Pressable style={[styles.sendSm, sending && styles.off]} onPress={addComment} disabled={sending}><Ionicons name="arrow-up" size={18} color="#fff" /></Pressable>
      </View>
    </View>
  );
}

// ─────────────────────────── DM (you↔bot) ───────────────────────────
function DmView({ headerPad, bottomInset }: { headerPad: number; bottomInset: number }) {
  const [msgs, setMsgs] = useState<{ role: 'user' | 'bot'; text: string }[]>([
    { role: 'bot', text: 'Здравствуйте! Я ИИ-агроном Flagleaf. Здесь мы говорим лично — спросите про препараты, ЭПВ, историю или план поля.' },
  ]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const kbOpen = useKeyboardOpen();
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
        contentContainerStyle={{ paddingHorizontal: 14, paddingTop: bottomInset + 72, paddingBottom: headerPad + 4, gap: 8 }} keyboardShouldPersistTaps="handled"
        renderItem={({ item }) => (
          <View style={[styles.bubble, item.role === 'user' ? styles.bubbleUser : styles.bubbleBot]}>
            <Text style={item.role === 'user' ? styles.bubbleUserTxt : styles.bubbleBotTxt}>{item.text}</Text>
          </View>
        )} />
      <KeyboardAvoidingView style={styles.composerHover} behavior={Platform.OS === 'ios' ? 'padding' : undefined} pointerEvents="box-none">
        <View style={{ marginBottom: kbOpen ? 0 : Math.max(bottomInset, 10) }}>
          <Composer value={text} onChange={setText} onSend={send} busy={busy} placeholder="Ваш вопрос агроному…" />
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

// ─────────────────── person DM (agronomist ↔ agronomist) ───────────────────
function PersonView({ peer, headerPad, bottomInset }: { peer: { id: number; name: string }; headerPad: number; bottomInset: number }) {
  const [msgs, setMsgs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const kbOpen = useKeyboardOpen();
  const load = useCallback(async () => {
    try { const d = await api.get(`/api/dm/with/${peer.id}`); setMsgs(d.messages || []); }
    catch {} finally { setLoading(false); }
  }, [peer.id]);
  useEffect(() => {
    load();
    const t = setInterval(load, 6000);    // near-live: poll the thread while it's open
    return () => clearInterval(t);
  }, [load]);
  const send = async () => {
    const b = text.trim(); if (!b || busy) return; setText(''); setBusy(true);
    setMsgs((m) => [...m, { id: `tmp-${m.length}`, mine: true, body: b }]);
    try { await api.postJson(`/api/dm/with/${peer.id}`, { body: b }); await load(); }
    catch {} finally { setBusy(false); }
  };
  return (
    <View style={{ flex: 1 }}>
      {loading ? <View style={styles.center}><ActivityIndicator color={GOLD} /></View> : (
        <FlatList data={[...msgs].reverse()} inverted keyExtractor={(m) => String(m.id)} style={StyleSheet.absoluteFill}
          contentContainerStyle={{ paddingHorizontal: 14, paddingTop: bottomInset + 72, paddingBottom: headerPad + 4, gap: 8 }} keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => (
            <View style={[styles.bubble, item.mine ? styles.bubbleUser : styles.bubbleBot]}>
              <Text style={item.mine ? styles.bubbleUserTxt : styles.bubbleBotTxt}>{item.body}</Text>
              {!!item.created_at && <Text style={[styles.bubbleTime, item.mine && { color: 'rgba(255,255,255,0.55)' }]}>{when(item.created_at)}</Text>}
            </View>
          )}
          ListEmptyComponent={<View style={styles.flip}><Text style={styles.empty}>Личная переписка с {peer.name}. Видите только вы двое.</Text></View>} />
      )}
      <KeyboardAvoidingView style={styles.composerHover} behavior={Platform.OS === 'ios' ? 'padding' : undefined} pointerEvents="box-none">
        <View style={{ marginBottom: kbOpen ? 0 : Math.max(bottomInset, 10) }}>
          <Composer value={text} onChange={setText} onSend={send} busy={busy} placeholder="Сообщение…" />
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: BG },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: BG },
  logo: { fontFamily: BRAND_FONT, fontWeight: '900', letterSpacing: 0.8, color: INK },
  off: { opacity: 0.5 },
  // login
  h1: { fontSize: 22, fontWeight: '600', marginTop: 18, color: INK },
  lead: { fontSize: 14, color: MUTED, lineHeight: 20, marginTop: 6, marginBottom: 18 },
  fld: { fontSize: 13, color: MUTED, marginBottom: 6 },
  input: { borderWidth: 1, borderColor: LINE, borderRadius: 14, padding: 14, fontSize: 16, backgroundColor: '#fff', color: INK },
  code: { letterSpacing: 8, textAlign: 'center', fontSize: 22 },
  btn: { backgroundColor: GOLD, borderRadius: 24, padding: 15, alignItems: 'center', marginTop: 12, ...softShadow, shadowColor: GOLD, shadowOpacity: 0.35 },
  btnTxt: { color: '#fff', fontWeight: '600', fontSize: 15 },
  note: { marginTop: 12, fontSize: 13, color: INK },
  help: { marginTop: 16, fontSize: 13, color: MUTED, lineHeight: 19 },
  // glass chrome
  headerGlass: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: 'rgba(120,90,30,0.12)' },
  headerRow: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12 },
  hdrRight: { marginLeft: 'auto', fontSize: 12, color: MUTED },
  // chat-list home
  chatRow: { flexDirection: 'row', alignItems: 'center', gap: 13, paddingHorizontal: 16, paddingVertical: 13 },
  rowAvLg: { width: 54, height: 54, borderRadius: 27, alignItems: 'center', justifyContent: 'center' },
  rowAv: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  avGroup: { backgroundColor: GOLD },
  avBot: { backgroundColor: INK },
  avPerson: { backgroundColor: '#e8dfc8' },
  avInitials: { color: '#6b541f', fontFamily: BRAND_FONT, fontWeight: '800', fontSize: 17 },
  avInitialsSm: { color: '#fff', fontFamily: BRAND_FONT, fontWeight: '800', fontSize: 13 },
  unreadBadge: { minWidth: 21, height: 21, borderRadius: 11, backgroundColor: GOLD, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6, marginLeft: 8, marginTop: 3 },
  unreadTxt: { color: '#fff', fontSize: 12, fontWeight: '700' },
  flip: { transform: [{ scaleY: -1 }] },
  bubbleTime: { fontSize: 10.5, color: MUTED, marginTop: 3, alignSelf: 'flex-end' },
  rowTop: { flexDirection: 'row', alignItems: 'center' },
  rowTitle: { fontSize: 16.5, fontFamily: BRAND_FONT, fontWeight: '800', color: INK, flexShrink: 1 },
  rowTime: { fontSize: 12, color: MUTED },
  rowPreview: { fontSize: 14, color: MUTED, marginTop: 3 },
  // chat header (inside an open conversation)
  chatHdrBg: { backgroundColor: 'rgba(250,247,241,0.96)' },
  chatHdrRow: { flexDirection: 'row', alignItems: 'center', paddingLeft: 4, paddingRight: 16, paddingVertical: 9, gap: 8 },
  backBtn: { paddingVertical: 6, paddingRight: 6, flexDirection: 'row', alignItems: 'center' },
  backTxt: { fontSize: 17, color: GOLD, marginLeft: -3 },
  chatHdrTitle: { fontSize: 16, fontFamily: BRAND_FONT, fontWeight: '800', color: INK, flexShrink: 1 },
  edgeStrip: { position: 'absolute', left: 0, bottom: 0, width: 30 },
  empty: { textAlign: 'center', color: MUTED, fontSize: 14, padding: 24, lineHeight: 20 },
  // post card
  post: { backgroundColor: '#fff', borderRadius: 22, padding: 14, ...softShadow },
  phead: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 9 },
  pav: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#e8dfc8', alignItems: 'center', justifyContent: 'center' },
  pavTxt: { color: '#6b541f', fontWeight: '600', fontSize: 14 },
  pauth: { fontWeight: '600', color: INK, fontSize: 14.5 },
  pmeta: { color: MUTED, fontSize: 12, marginTop: 1 },
  pbody: { fontSize: 15, lineHeight: 22, color: INK },
  pmedia: { width: '100%', height: 210, borderRadius: 16, backgroundColor: '#dfe6d3', marginTop: 10 },
  videoBox: { height: 140, borderRadius: 16, backgroundColor: '#dfe6d3', alignItems: 'center', justifyContent: 'center', marginTop: 10 },
  botPanel: { backgroundColor: '#faf4e6', borderRadius: 18, padding: 12, marginTop: 11 },
  botLabel: { flexDirection: 'row', alignItems: 'center', marginBottom: 4 },
  botLabelTxt: { color: '#9a7b1e', fontSize: 12.5, fontFamily: BRAND_FONT, fontWeight: '800', letterSpacing: 0.3 },
  botTxt: { fontSize: 13.5, lineHeight: 20, color: '#2a2418' },
  actRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 11 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 11, paddingVertical: 6, borderRadius: 20 },
  pillOk: { backgroundColor: '#eaf3e2' }, pillBad: { backgroundColor: '#fbeceb' },
  pillTxt: { fontSize: 12, fontWeight: '600' },
  cmtCount: { flexDirection: 'row', alignItems: 'center', marginLeft: 'auto' },
  cmtCountTxt: { fontSize: 12.5, color: MUTED },
  cmt: { backgroundColor: '#f5f1e8', borderRadius: 16, padding: 10, marginTop: 8 },
  ca: { fontWeight: '600', color: INK },
  cb: { fontSize: 13.5, lineHeight: 19, color: '#2a2418' },
  cmtForm: { flexDirection: 'row', gap: 8, marginTop: 10, alignItems: 'center' },
  cinputSm: { flex: 1, borderRadius: 20, height: 40, paddingHorizontal: 14, fontSize: 15, backgroundColor: '#f3eee2', color: INK },
  sendSm: { backgroundColor: GOLD, borderRadius: 20, width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  // dm bubbles
  bubble: { maxWidth: '86%', borderRadius: 20, paddingHorizontal: 14, paddingVertical: 10 },
  bubbleBot: { alignSelf: 'flex-start', backgroundColor: '#fff', ...softShadow, shadowOpacity: 0.06 },
  bubbleUser: { alignSelf: 'flex-end', backgroundColor: INK },
  bubbleBotTxt: { fontSize: 15, lineHeight: 21, color: INK },
  bubbleUserTxt: { fontSize: 15, lineHeight: 21, color: '#fff' },
  // composer
  composerHover: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  composer: { flexDirection: 'row', gap: 9, paddingHorizontal: 12, paddingVertical: 9, alignItems: 'flex-end' },
  iconCircle: { width: 42, height: 42, borderRadius: 21, borderWidth: 1, borderColor: '#e4dcca', alignItems: 'center', justifyContent: 'center' },
  capsule: { flex: 1, minHeight: 42, maxHeight: 120, borderRadius: 22, paddingHorizontal: 16, paddingTop: 11, paddingBottom: 11, fontSize: 16, backgroundColor: '#f3eee2', color: INK },
  sendCircle: { width: 44, height: 44, borderRadius: 22, backgroundColor: GOLD, alignItems: 'center', justifyContent: 'center', ...softShadow, shadowColor: GOLD, shadowOpacity: 0.4 },
});
