import * as DocumentPicker from 'expo-document-picker';
import { useState } from 'react';
import { Alert, Pressable, SafeAreaView, StyleSheet, Text, TextInput } from 'react-native';

import { api } from '@/src/api';
import GlassCard from '@/src/ui/GlassCard';
import NeonBackground from '@/src/ui/NeonBackground';
import { colors } from '@/src/ui/theme';

export default function UploadScreen() {
  const [fileName, setFileName] = useState('');
  const [workspaceId, setWorkspaceId] = useState('');
  const [loading, setLoading] = useState(false);

  async function pickAndUpload() {
    const picked = await DocumentPicker.getDocumentAsync({ type: ['application/pdf'], multiple: false, copyToCacheDirectory: true });
    if (picked.canceled || !picked.assets?.length) return;

    const file = picked.assets[0];
    setFileName(file.name);
    setLoading(true);
    try {
      await api.uploadDocument({ uri: file.uri, name: file.name, type: file.mimeType || 'application/pdf' }, workspaceId.trim() || undefined);
      Alert.alert('Thành công', 'Tài liệu đã được tải lên');
    } catch (error: any) {
      Alert.alert('Upload thất bại', error?.message || 'Không thể tải lên');
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={styles.root}>
      <NeonBackground />
      <GlassCard style={styles.card}>
        <Text style={styles.title}>Tải lên tài liệu</Text>
        <Text style={styles.sub}>Gắn file PDF vào workspace AI của bạn</Text>
        <TextInput style={styles.input} placeholder="Workspace ID (tùy chọn)" placeholderTextColor={colors.textSoft} value={workspaceId} onChangeText={setWorkspaceId} autoCapitalize="none" />
        <Pressable onPress={pickAndUpload} style={styles.button}><Text style={styles.buttonText}>{loading ? 'Đang tải...' : 'Chọn PDF và tải lên'}</Text></Pressable>
        {fileName ? <Text style={styles.file}>Đã chọn: {fileName}</Text> : null}
      </GlassCard>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg0, padding: 16 },
  card: { gap: 10 },
  title: { color: colors.text, fontSize: 26, fontWeight: '800' },
  sub: { color: colors.textSoft },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, color: colors.text, backgroundColor: 'rgba(255,255,255,0.92)' },
  button: { minHeight: 44, borderRadius: 12, backgroundColor: colors.cyan, alignItems: 'center', justifyContent: 'center' },
  buttonText: { color: '#ffffff', fontWeight: '800' },
  file: { color: colors.textSoft },
});
