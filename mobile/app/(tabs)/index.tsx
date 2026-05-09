import { Link } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { api } from '@/src/api';
import GlassCard from '@/src/ui/GlassCard';
import NeonBackground from '@/src/ui/NeonBackground';
import { colors } from '@/src/ui/theme';

type WorkspaceItem = { id: string; title: string; documents: any[] };

export default function HomeScreen() {
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setMessage('');
    try {
      const response = await api.listWorkspaces({ page_size: 24 });
      const items = Array.isArray(response) ? response : response?.items || response?.data || [];
      setWorkspaces(items);

      const untitledItems = items.filter((item) => shouldShowDeleteUntitled(item.title));
      const updates = untitledItems
        .map((item) => ({ item, nextTitle: getLatestDocumentTitle(item).trim() }))
        .filter((entry) => entry.nextTitle);

      if (updates.length) {
        await Promise.allSettled(
          updates.map(({ item, nextTitle }) =>
            api.updateWorkspace(item.id, { title: nextTitle }).then(() => ({ id: item.id, title: nextTitle }))
          )
        );

        setWorkspaces((current) =>
          current.map((ws) => {
            const found = updates.find((u) => u.item.id === ws.id);
            return found ? { ...ws, title: found.nextTitle } : ws;
          })
        );
      }
    } catch (error: any) {
      setMessage(error?.message || 'Không tải được workspace');
      setWorkspaces([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    if (!query.trim()) return workspaces;
    return workspaces.filter((item) => item.title?.toLowerCase().includes(query.toLowerCase()));
  }, [query, workspaces]);

  async function createWorkspace() {
    setCreating(true);
    try {
      await api.createWorkspace('Sổ ghi chú mới');
      await load();
    } catch (error: any) {
      setMessage(error?.message || 'Không tạo được workspace');
    } finally {
      setCreating(false);
    }
  }

  async function saveWorkspaceTitle(workspaceId: string, nextTitle: string) {
    const cleanTitle = nextTitle.trim();
    if (!cleanTitle) return;
    try {
      await api.updateWorkspace(workspaceId, { title: cleanTitle });
      setWorkspaces((items) => items.map((item) => (item.id === workspaceId ? { ...item, title: cleanTitle } : item)));
      setEditingId(null);
      setRenameValue('');
    } catch (error: any) {
      Alert.alert('Cập nhật thất bại', error?.message || 'Không thể đổi tên workspace');
    }
  }

  function getLatestDocumentTitle(workspace: WorkspaceItem) {
    const docs = workspace.documents || [];
    if (!docs.length) return "";
    const sorted = [...docs].sort((a, b) => {
      const aTime = new Date(a?.created_at || a?.raw?.created_at || 0).getTime();
      const bTime = new Date(b?.created_at || b?.raw?.created_at || 0).getTime();
      return bTime - aTime;
    });
    const latestDoc = sorted[0];
    return (
      latestDoc?.metadata?.title ||
      latestDoc?.title ||
      latestDoc?.filename ||
      ''
    );
  }

  function shouldShowDeleteUntitled(title?: string) {
    const clean = (title || '').trim().toLowerCase();
    return clean === 'untitled notebook' || clean === 'sổ ghi chú mới' || clean === 'so ghi chu moi';
  }

  function confirmDeleteWorkspace(workspace: WorkspaceItem) {
    Alert.alert(
      'Xóa workspace',
      `Bạn có chắc muốn xóa "${workspace.title || 'workspace này'}" không?`,
      [
        { text: 'Hủy', style: 'cancel' },
        {
          text: 'Xóa',
          style: 'destructive',
          onPress: async () => {
            try {
              await api.deleteWorkspace(workspace.id);
              setWorkspaces((items) => items.filter((item) => item.id !== workspace.id));
              await load();
            } catch (error: any) {
              Alert.alert('Xóa thất bại', error?.message || 'Không thể xóa workspace');
            }
          },
        },
      ]
    );
  }

  return (
    <View style={styles.root}>
      <NeonBackground />
      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.cyan} />}>
        <Text style={styles.title}>Không gian làm việc AI</Text>
        <Text style={styles.sub}>Quản lý workspace và tài liệu của bạn</Text>

        <GlassCard style={styles.searchWrap}>
          <TextInput style={styles.input} value={query} onChangeText={setQuery} placeholder="Tìm workspace" placeholderTextColor={colors.textSoft} />
          <Pressable style={styles.createBtn} disabled={creating} onPress={createWorkspace}>
            <Text style={styles.createBtnText}>{creating ? 'Đang tạo...' : 'Tạo mới'}</Text>
          </Pressable>
        </GlassCard>

        {message ? <Text style={styles.banner}>{message}</Text> : null}

        <View style={styles.grid}>
          {filtered.map((workspace) => {
            return (
              <GlassCard key={workspace.id} style={styles.card}>
                <Text style={styles.cardTitle}>{workspace.title || 'Sổ ghi chú chưa đặt tên'}</Text>
                <Text style={styles.cardMeta}>{workspace.documents?.length || 0} tài liệu liên kết</Text>
                {editingId === workspace.id ? (
                  <View style={styles.renameWrap}>
                    <TextInput
                      style={styles.input}
                      value={renameValue}
                      onChangeText={setRenameValue}
                      placeholder="Nhập tên workspace"
                      placeholderTextColor={colors.textSoft}
                    />
                    <View style={styles.actionRow}>
                      <Pressable style={styles.subBtn} onPress={() => setEditingId(null)}>
                        <Text style={styles.subBtnText}>Hủy</Text>
                      </Pressable>
                      <Pressable
                        style={styles.subBtnPrimary}
                        onPress={() => saveWorkspaceTitle(workspace.id, renameValue)}
                      >
                        <Text style={styles.subBtnPrimaryText}>Lưu</Text>
                      </Pressable>
                    </View>
                  </View>
                ) : (
                  <View style={styles.actionRow}>
                    <Pressable
                      style={styles.subBtn}
                      onPress={() => {
                        setEditingId(workspace.id);
                        setRenameValue(workspace.title || '');
                      }}
                    >
                      <Text style={styles.subBtnText}>Sửa tên</Text>
                    </Pressable>
                    {shouldShowDeleteUntitled(workspace.title) ? (
                      <Pressable style={styles.subBtnDanger} onPress={() => confirmDeleteWorkspace(workspace)}>
                        <Text style={styles.subBtnDangerText}>Xóa</Text>
                      </Pressable>
                    ) : null}
                  </View>
                )}
                <Link href={`/workspace/${workspace.id}`} asChild>
                  <Pressable style={styles.cardBtn}><Text style={styles.cardBtnText}>Mở workspace</Text></Pressable>
                </Link>
                {!workspace.documents?.length ? <Text style={styles.noDoc}>Chưa có tài liệu. Hãy dùng tab Tải lên.</Text> : null}
              </GlassCard>
            );
          })}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg0 },
  container: { padding: 16, paddingBottom: 100 },
  title: { color: colors.text, fontSize: 30, fontWeight: '800' },
  sub: { color: colors.textSoft, marginTop: 2, marginBottom: 10 },
  searchWrap: { gap: 10 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, color: colors.text, backgroundColor: 'rgba(255,255,255,0.92)', paddingHorizontal: 12, paddingVertical: 10 },
  createBtn: { minHeight: 44, borderRadius: 12, backgroundColor: colors.cyan, alignItems: 'center', justifyContent: 'center' },
  createBtnText: { color: '#ffffff', fontWeight: '800' },
  banner: { color: colors.danger, marginTop: 10 },
  grid: { marginTop: 14, gap: 10 },
  card: { gap: 8 },
  cardTitle: { color: colors.text, fontSize: 18, fontWeight: '700' },
  cardMeta: { color: colors.textSoft },
  renameWrap: { gap: 8 },
  actionRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  subBtn: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 8,
    backgroundColor: 'rgba(255,255,255,0.85)',
  },
  subBtnText: { color: colors.text, fontWeight: '600' },
  subBtnPrimary: {
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: colors.blue,
  },
  subBtnPrimaryText: { color: '#fff', fontWeight: '700' },
  subBtnDanger: {
    borderWidth: 1,
    borderColor: 'rgba(225,29,72,0.35)',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: 'rgba(225,29,72,0.08)',
  },
  subBtnDangerText: { color: colors.danger, fontWeight: '700' },
  cardBtn: { minHeight: 38, borderRadius: 10, backgroundColor: 'rgba(67,246,255,0.18)', borderWidth: 1, borderColor: 'rgba(67,246,255,0.45)', alignItems: 'center', justifyContent: 'center' },
  cardBtnText: { color: colors.cyan, fontWeight: '700' },
  noDoc: { color: colors.textSoft },
});
