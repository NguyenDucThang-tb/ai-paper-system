import { Link, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { api } from '@/src/api';
import GlassCard from '@/src/ui/GlassCard';
import NeonBackground from '@/src/ui/NeonBackground';
import { colors } from '@/src/ui/theme';

export default function WorkspaceDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [workspace, setWorkspace] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setMessage('');
    try {
      const data = await api.getWorkspace(String(id));
      setWorkspace(data);
    } catch (error: any) {
      setMessage(error?.message || 'Không tải được workspace');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const docs = workspace?.documents || [];

  return (
    <View style={styles.root}>
      <NeonBackground />
      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.cyan} />}>
        <Text style={styles.title}>{workspace?.title || 'Workspace'}</Text>
        <Text style={styles.sub}>{docs.length} tài liệu</Text>
        {message ? <Text style={styles.error}>{message}</Text> : null}

        {docs.length ? (
          docs.map((doc: any) => (
            <GlassCard key={doc.id} style={styles.card}>
              <Text style={styles.docTitle}>{doc?.metadata?.title || doc?.filename || `Tài liệu ${doc.id}`}</Text>
              <Text style={styles.docMeta}>{doc?.status || 'uploaded'}</Text>
              <Link href={`/document/${doc.id}`} asChild>
                <Pressable style={styles.openBtn}><Text style={styles.openBtnText}>Mở tài liệu</Text></Pressable>
              </Link>
            </GlassCard>
          ))
        ) : (
          <GlassCard style={styles.card}>
            <Text style={styles.docMeta}>Workspace này chưa có tài liệu.</Text>
          </GlassCard>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg0 },
  container: { padding: 16, paddingBottom: 40, gap: 10 },
  title: { color: colors.text, fontSize: 28, fontWeight: '800' },
  sub: { color: colors.textSoft, marginBottom: 6 },
  error: { color: colors.danger },
  card: { gap: 8 },
  docTitle: { color: colors.text, fontWeight: '700', fontSize: 16 },
  docMeta: { color: colors.textSoft },
  openBtn: { minHeight: 40, borderRadius: 10, backgroundColor: colors.cyan, alignItems: 'center', justifyContent: 'center' },
  openBtnText: { color: '#fff', fontWeight: '700' },
});
