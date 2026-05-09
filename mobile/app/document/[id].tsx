import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { api } from '@/src/api';
import { mapDocument } from '@/src/mappers';
import GlassCard from '@/src/ui/GlassCard';
import NeonBackground from '@/src/ui/NeonBackground';
import { colors } from '@/src/ui/theme';

export default function DocumentDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [doc, setDoc] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);
  const [qaHistory, setQaHistory] = useState<any[]>([]);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const [detail, sum, qa, rec, time] = await Promise.allSettled([
        api.getDocument(id),
        api.getSummary(id),
        api.getQaHistory(id),
        api.getRecommendations(id),
        api.getDocumentTimeline(id),
      ]);

      if (detail.status === 'fulfilled') setDoc(mapDocument(detail.value));
      if (sum.status === 'fulfilled') setSummary(sum.value);
      if (qa.status === 'fulfilled') setQaHistory(Array.isArray(qa.value) ? qa.value : qa.value?.items || []);
      if (rec.status === 'fulfilled') setRecommendations(rec.value?.items || rec.value || []);
      if (time.status === 'fulfilled') setTimeline(Array.isArray(time.value) ? time.value : time.value?.items || []);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function ask() {
    if (!id || !question.trim()) return;
    setBusy('qa');
    try {
      const payload = await api.requestQuestion(id, question);
      setAnswer(payload);
      setQuestion('');
      await load();
    } catch (error: any) {
      Alert.alert('Thất bại', error?.message || 'Gửi câu hỏi thất bại');
    } finally {
      setBusy('');
    }
  }

  async function generateSummary(level: 'short' | 'medium' | 'long') {
    if (!id) return;
    setBusy(`summary-${level}`);
    try {
      const payload = await api.requestSummary(id, level);
      Alert.alert('Đã tạo job tóm tắt', `Job #${payload?.job_id || ''}`);
    } catch (error: any) {
      Alert.alert('Thất bại', error?.message || 'Không yêu cầu được tóm tắt');
    } finally {
      setBusy('');
    }
  }

  async function removeDocument() {
    if (!id) return;
    try {
      await api.deleteDocument(id);
      Alert.alert('Đã xóa', 'Tài liệu đã được xóa');
    } catch (error: any) {
      Alert.alert('Xóa thất bại', error?.message || 'Không thể xóa tài liệu');
    }
  }

  const summaryText = useMemo(() => {
    if (!summary) return 'Chưa có tóm tắt.';
    if (typeof summary === 'string') return summary;
    return summary.summary || summary.content || JSON.stringify(summary, null, 2);
  }, [summary]);

  return (
    <View style={styles.root}>
      <NeonBackground />
      <ScrollView contentContainerStyle={styles.content} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.cyan} />}>
        <GlassCard style={styles.card}>
          <Text style={styles.title}>{doc?.title || 'Tài liệu'}</Text>
          <Text style={styles.meta}>{doc?.authors}</Text>
          <Text style={styles.meta}>Trạng thái: {doc?.status}</Text>
        </GlassCard>

        <GlassCard style={styles.card}>
          <Text style={styles.section}>Tóm tắt AI</Text>
          <Text style={styles.text}>{summaryText}</Text>
          <View style={styles.rowBtns}>
            <Pressable style={styles.tagBtn} onPress={() => generateSummary('short')}><Text style={styles.tagBtnText}>{busy === 'summary-short' ? '...' : 'Ngắn'}</Text></Pressable>
            <Pressable style={styles.tagBtn} onPress={() => generateSummary('medium')}><Text style={styles.tagBtnText}>{busy === 'summary-medium' ? '...' : 'Trung bình'}</Text></Pressable>
            <Pressable style={styles.tagBtn} onPress={() => generateSummary('long')}><Text style={styles.tagBtnText}>{busy === 'summary-long' ? '...' : 'Dài'}</Text></Pressable>
          </View>
        </GlassCard>

        <GlassCard style={styles.card}>
          <Text style={styles.section}>Hỏi đáp AI</Text>
          <TextInput style={styles.input} value={question} onChangeText={setQuestion} placeholder="Nhập câu hỏi về tài liệu này" placeholderTextColor={colors.textSoft} multiline />
          <Pressable style={styles.button} onPress={ask}><Text style={styles.buttonText}>{busy === 'qa' ? 'Đang gửi...' : 'Gửi câu hỏi'}</Text></Pressable>
          {answer ? <Text style={styles.text}>{JSON.stringify(answer, null, 2)}</Text> : null}
          {qaHistory.map((item, idx) => (
            <View key={`${idx}-${item.question || 'qa'}`} style={styles.subCard}>
              <Text style={styles.q}>Q: {item.question || '-'}</Text>
              <Text style={styles.a}>A: {item.answer || '-'}</Text>
            </View>
          ))}
        </GlassCard>

        <GlassCard style={styles.card}>
          <Text style={styles.section}>Gợi ý tài liệu</Text>
          {recommendations.length ? recommendations.slice(0, 10).map((item, idx) => (
            <View key={`${idx}-${item.title || 'r'}`} style={styles.subCard}>
              <Text style={styles.q}>{item.title || `Mục ${idx + 1}`}</Text>
              <Text style={styles.a}>{item.reason || item.abstract || '-'}</Text>
            </View>
          )) : <Text style={styles.meta}>Chưa có gợi ý.</Text>}
        </GlassCard>

        <GlassCard style={styles.card}>
          <Text style={styles.section}>Lịch sử xử lý</Text>
          {timeline.length ? timeline.slice(0, 20).map((item, idx) => (
            <Text key={`${idx}-${item.status || 't'}`} style={styles.text}>{item.status || item.event || '-'} - {item.created_at || item.timestamp || ''}</Text>
          )) : <Text style={styles.meta}>Chưa có lịch sử.</Text>}
        </GlassCard>

        <Pressable style={styles.delete} onPress={removeDocument}><Text style={styles.deleteText}>Xóa tài liệu</Text></Pressable>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg0 },
  content: { padding: 16, paddingBottom: 40, gap: 10 },
  card: { gap: 8 },
  subCard: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, padding: 10, gap: 6, backgroundColor: 'rgba(255,255,255,0.86)' },
  title: { color: colors.text, fontSize: 24, fontWeight: '800' },
  section: { color: colors.text, fontSize: 18, fontWeight: '700' },
  meta: { color: colors.textSoft },
  text: { color: colors.text },
  q: { color: colors.text, fontWeight: '700' },
  a: { color: colors.textSoft },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, minHeight: 86, paddingHorizontal: 12, paddingVertical: 10, textAlignVertical: 'top', color: colors.text, backgroundColor: 'rgba(255,255,255,0.92)' },
  rowBtns: { flexDirection: 'row', gap: 8 },
  tagBtn: { borderWidth: 1, borderColor: colors.border, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6, backgroundColor: 'rgba(14,165,233,0.08)' },
  tagBtnText: { color: colors.cyan, fontWeight: '700' },
  button: { minHeight: 42, borderRadius: 12, backgroundColor: colors.cyan, alignItems: 'center', justifyContent: 'center' },
  buttonText: { color: '#ffffff', fontWeight: '800' },
  delete: { marginTop: 4, borderWidth: 1, borderColor: 'rgba(225,29,72,0.25)', borderRadius: 12, minHeight: 44, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(225,29,72,0.08)' },
  deleteText: { color: colors.danger, fontWeight: '700' },
});
