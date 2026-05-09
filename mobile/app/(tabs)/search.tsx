import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { api } from '@/src/api';
import GlassCard from '@/src/ui/GlassCard';
import NeonBackground from '@/src/ui/NeonBackground';
import { colors } from '@/src/ui/theme';

export default function SearchScreen() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  async function runSearch() {
    setLoading(true);
    setMessage('');
    try {
      const payload = await api.search(query, 10);
      const items = Array.isArray(payload) ? payload : payload?.items || payload?.results || [];
      setResults(items);
      if (!items.length) setMessage('Không có kết quả phù hợp.');
    } catch (error: any) {
      setResults([]);
      setMessage(error?.message || 'Tìm kiếm thất bại.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <View style={styles.root}>
      <NeonBackground />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Tìm kiếm AI</Text>
        <GlassCard style={styles.controls}>
          <TextInput style={styles.input} multiline placeholder="Nhập câu hỏi hoặc từ khóa nghiên cứu" placeholderTextColor={colors.textSoft} value={query} onChangeText={setQuery} />
          <Pressable onPress={runSearch} style={styles.button}><Text style={styles.buttonText}>{loading ? 'Đang tìm...' : 'Tìm kiếm'}</Text></Pressable>
        </GlassCard>
        {message ? <Text style={styles.message}>{message}</Text> : null}
        {results.map((item, index) => (
          <GlassCard key={item.id || item.document_id || index} style={styles.card}>
            <Text style={styles.cardTitle}>{item.title || item.filename || `Kết quả ${index + 1}`}</Text>
            <Text style={styles.cardText}>{item.snippet || item.answer || item.content || item.abstract || '-'}</Text>
          </GlassCard>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg0 },
  content: { padding: 16, paddingBottom: 100 },
  title: { fontSize: 28, fontWeight: '800', color: colors.text, marginBottom: 12 },
  controls: { gap: 10 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, minHeight: 110, padding: 12, textAlignVertical: 'top', color: colors.text, backgroundColor: 'rgba(255,255,255,0.92)' },
  button: { borderRadius: 12, minHeight: 44, backgroundColor: colors.cyan, alignItems: 'center', justifyContent: 'center' },
  buttonText: { color: '#ffffff', fontWeight: '800' },
  message: { marginTop: 12, color: colors.danger },
  card: { marginTop: 10 },
  cardTitle: { color: colors.text, fontWeight: '700' },
  cardText: { marginTop: 6, color: colors.textSoft },
});
