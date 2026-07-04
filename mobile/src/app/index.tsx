import { useEffect, useState, useCallback } from 'react';
import {
  ActivityIndicator, FlatList, Image, KeyboardAvoidingView, Platform,
  Pressable, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { api, getToken, setToken } from '@/lib/api';

const GOLD = '#b9994b', INK = '#1a1a1a', BG = '#faf8f4', LINE = '#e7e2d8', MUTED = '#8a8a8a';

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
function Logo() {
  return <Text style={styles.logo}><Text style={{ color: GOLD }}>E</Text>AR</Text>;
}

// ─────────────────────────── root ───────────────────────────
export default function App() {
  const [ready, setReady] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);

  useEffect(() => {
    (async () => {
      const tok = await getToken();
      if (tok) {
        try { await api.get('/api/me'); setLoggedIn(true); }
        catch { await setToken(null); }
      }
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
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const sendCode = async () => {
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { setNote('Введите корректный email.'); return; }
    setBusy(true); setNote('Отправляю код…');
    try { const r = await api.postJson('/api/auth/email/start', { email }); setNote(r?.message || 'Код отправлен на почту.'); }
    catch (e: any) { setNote(e?.message || 'Не удалось отправить код.'); }
    finally { setBusy(false); }
  };
  const verify = async () => {
    if (code.trim().length !== 6) { setNote('Введите 6 цифр кода.'); return; }
    setBusy(true); setNote('Проверяю…');
    try { const r = await api.postJson('/api/auth/verify', { code: code.trim() }); await setToken(r.token); onDone(); }
    catch (e: any) { setNote(e?.message || 'Не удалось войти.'); setBusy(false); }
  };

  return (
    <SafeAreaView style={styles.screen}>
      <View style={styles.loginWrap}>
        <Logo />
        <Text style={styles.h1}>Вход для агрономов</Text>
        <Text style={styles.lead}>ИИ-агроном, скаутинг и лента команды — для зарегистрированных агрономов хозяйства.</Text>

        <Text style={styles.fld}>Почта</Text>
        <TextInput style={styles.input} value={email} onChangeText={setEmail} placeholder="email"
          autoCapitalize="none" keyboardType="email-address" placeholderTextColor={MUTED} />
        <Pressable style={[styles.btn, busy && styles.btnOff]} onPress={sendCode} disabled={busy}>
          <Text style={styles.btnTxt}>Отправить код на почту</Text>
        </Pressable>

        <Text style={[styles.fld, { marginTop: 18 }]}>Код из письма</Text>
        <TextInput style={[styles.input, styles.code]} value={code} onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
          placeholder="——————" keyboardType="number-pad" maxLength={6} placeholderTextColor={MUTED} />
        <Pressable style={[styles.btn, busy && styles.btnOff]} onPress={verify} disabled={busy}>
          <Text style={styles.btnTxt}>Войти</Text>
        </Pressable>
        {!!note && <Text style={styles.note}>{note}</Text>}
        <Text style={styles.help}>Нет почты в системе — получите код в Telegram-боте Flagleaf командой /weblogin.</Text>
      </View>
    </SafeAreaView>
  );
}

// ─────────────────────────── logged-in shell (tabs) ───────────────────────────
function Main({ onLogout }: { onLogout: () => void }) {
  const [me, setMe] = useState<any>(null);
  const [tab, setTab] = useState<'feed' | 'dm'>('feed');
  useEffect(() => { api.get('/api/me').then(setMe).catch(() => {}); }, []);

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <View style={styles.header}>
        <Logo />
        <Text style={styles.hdrRight}>{me?.name || ''} · <Text style={{ color: GOLD }} onPress={onLogout}>выйти</Text></Text>
      </View>
      <View style={styles.tabbar}>
        <Pressable style={styles.tab} onPress={() => setTab('feed')}>
          <Text style={[styles.tabTxt, tab === 'feed' && styles.tabOn]}>👥 Лента</Text>
        </Pressable>
        <Pressable style={styles.tab} onPress={() => setTab('dm')}>
          <Text style={[styles.tabTxt, tab === 'dm' && styles.tabOn]}>💬 Личное</Text>
        </Pressable>
      </View>
      {tab === 'feed' ? <FeedView onLogout={onLogout} /> : <DmView />}
    </SafeAreaView>
  );
}

// ─────────────────────────── feed ───────────────────────────
function FeedView({ onLogout }: { onLogout: () => void }) {
  const insets = useSafeAreaInsets();
  const [posts, setPosts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { const d = await api.get('/api/feed'); setPosts(d.posts || []); }
    catch (e: any) { if (e?.status === 401) onLogout(); }
    finally { setLoading(false); }
  }, [onLogout]);
  useEffect(() => { load(); }, [load]);

  const publish = async () => {
    const b = text.trim(); if (!b) return; setText(''); setBusy(true);
    try { await api.postForm('/api/feed/post', formData({ body: b })); await load(); }
    catch {} finally { setBusy(false); }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      {loading ? (
        <View style={styles.center}><ActivityIndicator color={GOLD} /></View>
      ) : (
        <FlatList
          data={posts}
          inverted
          keyExtractor={(p) => String(p.id)}
          contentContainerStyle={{ padding: 12, gap: 12 }}
          keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => <PostCard p={item} onChanged={load} />}
          ListEmptyComponent={<Text style={styles.empty}>Пока пусто. Напишите наблюдение — оно появится здесь для всей команды.</Text>}
        />
      )}
      <View style={[styles.composer, { paddingBottom: Math.max(insets.bottom, 8) }]}>
        <TextInput style={styles.cinput} value={text} onChangeText={setText}
          placeholder="Наблюдение с поля или вопрос команде…" placeholderTextColor={MUTED} multiline />
        <Pressable style={[styles.send, busy && styles.btnOff]} onPress={publish} disabled={busy}>
          <Text style={styles.sendTxt}>➤</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

function PostCard({ p, onChanged }: { p: any; onChanged: () => void }) {
  const [c, setC] = useState('');
  const [sending, setSending] = useState(false);
  const addComment = async () => {
    const b = c.trim(); if (!b) return; setC(''); setSending(true);
    try { await api.postJson(`/api/feed/${p.id}/comment`, { body: b }); onChanged(); }
    catch {} finally { setSending(false); }
  };
  return (
    <View style={styles.post}>
      <View style={styles.phead}>
        <View style={styles.pav}><Text style={styles.pavTxt}>{initials(p.author)}</Text></View>
        <Text style={styles.pauth}>{p.author}</Text>
        <Text style={styles.pmeta}>{when(p.created_at)}{p.field ? `\n📍 ${p.field}` : ''}</Text>
      </View>
      {!!p.body && <Text style={styles.pbody}>{p.body}</Text>}
      {!!p.media && (p.is_video
        ? <View style={styles.videoBox}><Text style={{ color: MUTED }}>🎬 видео</Text></View>
        : <Image source={{ uri: p.media }} style={styles.pmedia} resizeMode="cover" />)}
      {(p.ups > 0 || p.downs > 0) && (
        <Text style={styles.verdict}>{p.ups > 0 ? '✓ подтвердил старший' : '✗ отклонил старший'}</Text>
      )}
      {(p.thread || []).length > 0 && (
        <View style={styles.thread}>
          {p.thread.map((cm: any) => (
            <View key={cm.id} style={[styles.cmt, cm.is_bot && styles.cmtBot]}>
              <Text style={styles.ca}>{cm.is_bot ? '🤖 ' : ''}{cm.author}{cm.chief ? '  •старший' : ''}</Text>
              <Text style={styles.cb}>{cm.body}</Text>
            </View>
          ))}
        </View>
      )}
      <View style={styles.cmtForm}>
        <TextInput style={styles.cinputSm} value={c} onChangeText={setC}
          placeholder="Ответить… («бот …» — спросить ИИ)" placeholderTextColor={MUTED} />
        <Pressable style={[styles.sendSm, sending && styles.btnOff]} onPress={addComment} disabled={sending}>
          <Text style={styles.sendTxt}>➤</Text>
        </Pressable>
      </View>
    </View>
  );
}

// ─────────────────────────── direct messaging (private you↔bot) ───────────────────────────
function DmView() {
  const insets = useSafeAreaInsets();
  const [msgs, setMsgs] = useState<{ role: 'user' | 'bot'; text: string }[]>([
    { role: 'bot', text: 'Здравствуйте! Я ИИ-агроном Flagleaf. Здесь мы говорим лично — спросите про препараты, ЭПВ, историю или план поля.' },
  ]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);

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
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <FlatList
        data={[...msgs].reverse()}
        inverted
        keyExtractor={(_, i) => String(i)}
        contentContainerStyle={{ padding: 12, gap: 8 }}
        keyboardShouldPersistTaps="handled"
        renderItem={({ item }) => (
          <View style={[styles.bubble, item.role === 'user' ? styles.bubbleUser : styles.bubbleBot]}>
            <Text style={item.role === 'user' ? styles.bubbleUserTxt : styles.bubbleBotTxt}>{item.text}</Text>
          </View>
        )}
      />
      <View style={[styles.composer, { paddingBottom: Math.max(insets.bottom, 8) }]}>
        <TextInput style={styles.cinput} value={text} onChangeText={setText}
          placeholder="Ваш вопрос агроному…" placeholderTextColor={MUTED} multiline />
        <Pressable style={[styles.send, busy && styles.btnOff]} onPress={send} disabled={busy}>
          <Text style={styles.sendTxt}>➤</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: BG },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: BG },
  logo: { fontWeight: '700', letterSpacing: 3, fontSize: 18, color: INK },
  // login
  loginWrap: { padding: 24, marginTop: 40 },
  h1: { fontSize: 22, fontWeight: '600', marginTop: 16, color: INK },
  lead: { fontSize: 14, color: MUTED, lineHeight: 20, marginTop: 6, marginBottom: 18 },
  fld: { fontSize: 13, color: MUTED, marginBottom: 6 },
  input: { borderWidth: 1, borderColor: LINE, borderRadius: 12, padding: 13, fontSize: 16, backgroundColor: '#fff', color: INK },
  code: { letterSpacing: 8, textAlign: 'center', fontSize: 22 },
  btn: { backgroundColor: GOLD, borderRadius: 12, padding: 14, alignItems: 'center', marginTop: 12 },
  btnOff: { opacity: 0.5 },
  btnTxt: { color: '#fff', fontWeight: '600', fontSize: 15 },
  note: { marginTop: 12, fontSize: 13, color: INK },
  help: { marginTop: 16, fontSize: 13, color: MUTED, lineHeight: 19 },
  // shell
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12, backgroundColor: '#fff', borderBottomWidth: 1, borderBottomColor: LINE },
  hdrRight: { marginLeft: 'auto', fontSize: 12, color: MUTED },
  tabbar: { flexDirection: 'row', backgroundColor: '#fff', borderBottomWidth: 1, borderBottomColor: LINE },
  tab: { flex: 1, paddingVertical: 10, alignItems: 'center' },
  tabTxt: { fontSize: 13, fontWeight: '600', color: MUTED, paddingBottom: 8, borderBottomWidth: 2, borderBottomColor: 'transparent' },
  tabOn: { color: INK, borderBottomColor: GOLD },
  empty: { textAlign: 'center', color: MUTED, fontSize: 14, padding: 24, lineHeight: 20 },
  // post
  post: { backgroundColor: '#fff', borderWidth: 1, borderColor: LINE, borderRadius: 14, padding: 12 },
  phead: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 },
  pav: { width: 30, height: 30, borderRadius: 15, backgroundColor: '#efe7d2', alignItems: 'center', justifyContent: 'center' },
  pavTxt: { color: '#6b541f', fontWeight: '600', fontSize: 12 },
  pauth: { fontWeight: '600', color: INK },
  pmeta: { marginLeft: 'auto', color: MUTED, fontSize: 12, textAlign: 'right' },
  pbody: { fontSize: 15, lineHeight: 21, color: INK, marginBottom: 8 },
  pmedia: { width: '100%', height: 220, borderRadius: 10, backgroundColor: '#f2eee4', marginBottom: 8 },
  videoBox: { height: 120, borderRadius: 10, backgroundColor: '#f2eee4', alignItems: 'center', justifyContent: 'center', marginBottom: 8 },
  verdict: { fontSize: 12, color: '#3a7d44', fontWeight: '500', marginBottom: 4 },
  thread: { gap: 8, marginTop: 8 },
  cmt: { backgroundColor: '#f4f1ea', borderRadius: 10, padding: 8 },
  cmtBot: { backgroundColor: '#faf6ec', borderWidth: 1, borderColor: '#eadfbf' },
  ca: { fontWeight: '600', fontSize: 13, color: INK, marginBottom: 3 },
  cb: { fontSize: 13.5, lineHeight: 19, color: INK },
  cmtForm: { flexDirection: 'row', gap: 6, marginTop: 8, alignItems: 'center' },
  cinputSm: { flex: 1, borderWidth: 1, borderColor: LINE, borderRadius: 10, height: 40, paddingHorizontal: 12, paddingVertical: 0, fontSize: 15, backgroundColor: '#fff', color: INK },
  sendSm: { backgroundColor: GOLD, borderRadius: 10, height: 40, paddingHorizontal: 14, alignItems: 'center', justifyContent: 'center' },
  // dm bubbles
  bubble: { maxWidth: '86%', borderRadius: 14, paddingHorizontal: 13, paddingVertical: 10 },
  bubbleBot: { alignSelf: 'flex-start', backgroundColor: '#fff', borderWidth: 1, borderColor: LINE },
  bubbleUser: { alignSelf: 'flex-end', backgroundColor: INK },
  bubbleBotTxt: { fontSize: 15, lineHeight: 21, color: INK },
  bubbleUserTxt: { fontSize: 15, lineHeight: 21, color: '#fff' },
  // composer
  composer: { flexDirection: 'row', gap: 6, paddingHorizontal: 10, paddingTop: 10, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: LINE, alignItems: 'flex-end' },
  cinput: { flex: 1, borderWidth: 1, borderColor: LINE, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16, maxHeight: 120, backgroundColor: '#fff', color: INK },
  send: { backgroundColor: GOLD, borderRadius: 12, height: 44, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center' },
  sendTxt: { color: '#fff', fontWeight: '600', fontSize: 16 },
});
