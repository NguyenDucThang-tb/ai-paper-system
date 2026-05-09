import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, SafeAreaView, StyleSheet, Text, TextInput, View } from 'react-native';

import { api } from '@/src/api';
import GlassCard from '@/src/ui/GlassCard';
import NeonBackground from '@/src/ui/NeonBackground';
import { colors } from '@/src/ui/theme';

export default function RegisterScreen() {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  async function onRegister() {
    setLoading(true);
    try {
      await api.register({ full_name: fullName || email, email, password });
      Alert.alert('Thành công', 'Đã tạo tài khoản');
      router.replace('/auth/login');
    } catch (error: any) {
      Alert.alert('Đăng ký thất bại', error?.message || 'Không thể đăng ký');
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={styles.root}>
      <NeonBackground />
      <View style={styles.wrap}>
        <GlassCard style={styles.card}>
          <Text style={styles.title}>Tạo tài khoản</Text>
          <TextInput style={styles.input} placeholder="Họ tên" placeholderTextColor={colors.textSoft} value={fullName} onChangeText={setFullName} />
          <TextInput style={styles.input} placeholder="Email" placeholderTextColor={colors.textSoft} autoCapitalize="none" value={email} onChangeText={setEmail} />
          <TextInput style={styles.input} placeholder="Mật khẩu" placeholderTextColor={colors.textSoft} secureTextEntry value={password} onChangeText={setPassword} />
          <Pressable onPress={onRegister} style={styles.button} disabled={loading || !email || !password}>
            <Text style={styles.buttonText}>{loading ? 'Đang tạo...' : 'Đăng ký'}</Text>
          </Pressable>
        </GlassCard>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg0 },
  wrap: { flex: 1, justifyContent: 'center', padding: 18 },
  card: { gap: 10 },
  title: { color: colors.text, fontSize: 26, fontWeight: '800', marginBottom: 4 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, color: colors.text, backgroundColor: 'rgba(255,255,255,0.92)', paddingHorizontal: 12, paddingVertical: 11 },
  button: { backgroundColor: colors.cyan, borderRadius: 12, minHeight: 46, alignItems: 'center', justifyContent: 'center' },
  buttonText: { color: '#ffffff', fontWeight: '800' },
});
