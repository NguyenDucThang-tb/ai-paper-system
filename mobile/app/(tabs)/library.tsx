import { Link } from 'expo-router';
import { useEffect, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { api } from '@/src/api';
import { mapDocuments, type ViewDocument } from '@/src/mappers';
import GlassCard from '@/src/ui/GlassCard';
import NeonBackground from '@/src/ui/NeonBackground';
import { colors } from '@/src/ui/theme';

export default function LibraryScreen() {
  const [documents, setDocuments] = useState<ViewDocument[]>([]);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const response = await api.listDocuments({ limit: 50 });
      setDocuments(mapDocuments(response));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <View style={styles.root}>
      <NeonBackground />
      <FlatList
        contentContainerStyle={styles.content}
        data={documents}
        keyExtractor={(item) => item.id}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.cyan} />}
        ListHeaderComponent={<Text style={styles.title}>Thư viện tài liệu</Text>}
        renderItem={({ item }) => (
          <Link href={`/document/${item.id}`} asChild>
            <Pressable>
              <GlassCard style={styles.row}>
                <Text style={styles.docTitle}>{item.title}</Text>
                <Text style={styles.docMeta}>{item.authors} · {item.year}</Text>
                <Text style={styles.pill}>{item.status}</Text>
              </GlassCard>
            </Pressable>
          </Link>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg0 },
  content: { padding: 16, paddingBottom: 110, gap: 10 },
  title: { fontSize: 28, fontWeight: '800', color: colors.text, marginBottom: 8 },
  row: { gap: 6 },
  docTitle: { color: colors.text, fontWeight: '700' },
  docMeta: { color: colors.textSoft, marginTop: 2 },
  pill: { marginTop: 6, color: colors.cyan, fontWeight: '600' },
});
