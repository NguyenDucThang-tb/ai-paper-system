import { Link, router } from 'expo-router';
import * as Google from 'expo-auth-session/providers/google';
import { useState } from 'react';
import { ActivityIndicator, Alert, Pressable, SafeAreaView, StyleSheet, Text, TextInput, View } from 'react-native';

import { api } from '@/src/api';
import GlassCard from '@/src/ui/GlassCard';
import NeonBackground from '@/src/ui/NeonBackground';
import { colors } from '@/src/ui/theme';

export default function LoginScreen() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [request, , promptAsync] = Google.useAuthRequest({
    expoClientId: process.env.EXPO_PUBLIC_GOOGLE_EXPO_CLIENT_ID,
    iosClientId: process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID,
    androidClientId: process.env.EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID,
    webClientId: process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID,
    scopes: ['openid', 'profile', 'email'],
  });

  async function onLogin() {
    setLoading(true);
    try {
      await api.login(email, password);
      router.replace('/(tabs)');
    } catch (error: any) {
      Alert.alert('Đăng nhập thất bại', error?.message || 'Không kết nối được backend');
    } finally {
      setLoading(false);
    }
  }

  async function onGoogleLogin() {
    if (!request) return;
    if (!process.env.EXPO_PUBLIC_GOOGLE_EXPO_CLIENT_ID && !process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID) {
      Alert.alert('Thiếu cấu hình', 'Hãy thêm EXPO_PUBLIC_GOOGLE_EXPO_CLIENT_ID vào mobile/.env');
      return;
    }
    setGoogleLoading(true);
    try {
      const result = await promptAsync();
      if (result.type !== 'success') return;
      const idToken = result.authentication?.idToken || result.params?.id_token;
      if (!idToken) {
        throw new Error('Không lấy được Google id_token');
      }
      await api.loginWithGoogle(idToken);
      router.replace('/(tabs)');
    } catch (error: any) {
      Alert.alert('Đăng nhập Google thất bại', error?.message || 'Không kết nối được backend');
    } finally {
      setGoogleLoading(false);
    }
  }

  return (
    <SafeAreaView style={styles.root}>
      <NeonBackground />
      <View style={styles.wrap}>
        <Text style={styles.brand}>AI PAPER</Text>
        <Text style={styles.tagline}>Không gian trí tuệ AI</Text>

        <GlassCard style={styles.card}>
          <Text style={styles.title}>Chào mừng bạn quay lại</Text>
          <Text style={styles.subtitle}>Đăng nhập để tiếp tục sử dụng AI Paper</Text>

          <TextInput style={styles.input} placeholder="Email" placeholderTextColor={colors.textSoft} autoCapitalize="none" value={email} onChangeText={setEmail} />
          <TextInput style={styles.input} placeholder="Mật khẩu" placeholderTextColor={colors.textSoft} secureTextEntry value={password} onChangeText={setPassword} />

          <Pressable style={styles.button} onPress={onLogin} disabled={loading || !email || !password}>
            {loading ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.buttonText}>Đăng nhập</Text>}
          </Pressable>

          <Pressable style={styles.googleButton} onPress={onGoogleLogin} disabled={googleLoading || !request}>
            {googleLoading ? <ActivityIndicator color="#0f172a" /> : <Text style={styles.googleButtonText}>Đăng nhập với Google</Text>}
          </Pressable>

          <View style={styles.links}>
            <Link href="/auth/register" style={styles.linkText}>Tạo tài khoản</Link>
            <Link href="/auth/forgot-password" style={styles.linkText}>Quên mật khẩu</Link>
          </View>

          <Text style={styles.api}>API: {api.apiBaseUrl}</Text>
        </GlassCard>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg0 },
  wrap: { flex: 1, justifyContent: 'center', padding: 18, gap: 10 },
  brand: { color: colors.cyan, letterSpacing: 4, fontWeight: '800', fontSize: 13 },
  tagline: { color: colors.textSoft, marginBottom: 8 },
  card: { gap: 10 },
  title: { color: colors.text, fontSize: 30, fontWeight: '800' },
  subtitle: { color: colors.textSoft, marginBottom: 6 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: 'rgba(255,255,255,0.92)',
    borderRadius: 12,
    color: colors.text,
    paddingHorizontal: 12,
    paddingVertical: 11,
  },
  button: {
    backgroundColor: colors.cyan,
    borderRadius: 12,
    minHeight: 46,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: colors.cyan,
    shadowOpacity: 0.45,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 8 },
  },
  buttonText: { color: '#ffffff', fontWeight: '800' },
  googleButton: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    minHeight: 46,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#ffffff',
  },
  googleButtonText: { color: '#0f172a', fontWeight: '700' },
  links: { flexDirection: 'row', justifyContent: 'space-between' },
  linkText: { color: colors.blue },
  api: { color: colors.textSoft, fontSize: 12, marginTop: 4 },
});
