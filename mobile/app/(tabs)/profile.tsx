import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Alert, Pressable, SafeAreaView, ScrollView, StyleSheet, Text, TextInput } from 'react-native';

import { api } from '@/src/api';
import { clearSession, getSessionState } from '@/src/session';
import GlassCard from '@/src/ui/GlassCard';
import NeonBackground from '@/src/ui/NeonBackground';
import { colors } from '@/src/ui/theme';

export default function ProfileScreen() {
  const [user, setUser] = useState<any>(getSessionState().user || null);
  const [fullName, setFullName] = useState('');
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');

  useEffect(() => {
    api.me().then((data) => {
      setUser(data);
      setFullName(data?.full_name || '');
    });
  }, []);

  async function updateProfile() {
    try {
      const payload = await api.updateProfile({ full_name: fullName });
      setUser(payload);
      Alert.alert('Thành công', 'Đã cập nhật hồ sơ');
    } catch (error: any) {
      Alert.alert('Thất bại', error?.message || 'Không cập nhật được hồ sơ');
    }
  }

  async function changePassword() {
    try {
      await api.changePassword({ old_password: oldPassword, new_password: newPassword });
      Alert.alert('Thành công', 'Đã đổi mật khẩu');
      setOldPassword('');
      setNewPassword('');
    } catch (error: any) {
      Alert.alert('Thất bại', error?.message || 'Không đổi được mật khẩu');
    }
  }

  async function logout() {
    await clearSession();
    router.replace('/auth/login');
  }

  return (
    <SafeAreaView style={styles.root}>
      <NeonBackground />
      <ScrollView contentContainerStyle={styles.content}>
        <GlassCard style={styles.card}>
          <Text style={styles.title}>Hồ sơ tài khoản</Text>
          <Text style={styles.meta}>{user?.email || '-'}</Text>
          <TextInput style={styles.input} value={fullName} onChangeText={setFullName} placeholder="Họ tên" placeholderTextColor={colors.textSoft} />
          <Pressable style={styles.button} onPress={updateProfile}><Text style={styles.buttonText}>Cập nhật hồ sơ</Text></Pressable>
        </GlassCard>

        <GlassCard style={styles.card}>
          <Text style={styles.section}>Bảo mật</Text>
          <TextInput style={styles.input} value={oldPassword} onChangeText={setOldPassword} placeholder="Mật khẩu cũ" placeholderTextColor={colors.textSoft} secureTextEntry />
          <TextInput style={styles.input} value={newPassword} onChangeText={setNewPassword} placeholder="Mật khẩu mới" placeholderTextColor={colors.textSoft} secureTextEntry />
          <Pressable style={styles.button} onPress={changePassword}><Text style={styles.buttonText}>Đổi mật khẩu</Text></Pressable>
        </GlassCard>

        <Pressable style={styles.logout} onPress={logout}><Text style={styles.logoutText}>Đăng xuất</Text></Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg0 },
  content: { padding: 16, gap: 12, paddingBottom: 100 },
  card: { gap: 8 },
  title: { color: colors.text, fontSize: 28, fontWeight: '800' },
  section: { color: colors.text, fontSize: 18, fontWeight: '700' },
  meta: { color: colors.textSoft },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, color: colors.text, backgroundColor: 'rgba(255,255,255,0.92)', paddingHorizontal: 12, paddingVertical: 10 },
  button: { backgroundColor: colors.cyan, minHeight: 42, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  buttonText: { color: '#ffffff', fontWeight: '800' },
  logout: { marginTop: 6, borderWidth: 1, borderColor: 'rgba(225,29,72,0.25)', borderRadius: 12, minHeight: 44, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(225,29,72,0.08)' },
  logoutText: { color: colors.danger, fontWeight: '700' },
});
