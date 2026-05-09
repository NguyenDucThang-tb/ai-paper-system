import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Alert, Pressable, SafeAreaView, StyleSheet, Text, TextInput, View } from 'react-native';

import { api } from '@/src/api';
import GlassCard from '@/src/ui/GlassCard';
import NeonBackground from '@/src/ui/NeonBackground';
import { colors } from '@/src/ui/theme';

export default function ForgotPasswordScreen() {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [step, setStep] = useState<'send' | 'verify' | 'reset'>('send');
  const [loading, setLoading] = useState(false);

  async function sendCode() {
    setLoading(true);
    try {
      const res = await api.sendForgotPasswordCode(email);
      setStep('verify');
      Alert.alert('Đã gửi OTP', 'Vui lòng kiểm tra email');
      if (res?.message) {
        Alert.alert('Thông báo', res.message);
      }
    } catch (error: any) {
      Alert.alert('Thất bại', error?.message || 'Không gửi được OTP');
    } finally {
      setLoading(false);
    }
  }

  async function verifyCode() {
    setLoading(true);
    try {
      await api.verifyForgotPasswordCode(email, code);
      setStep('reset');
      Alert.alert('Thành công', 'Xác nhận mã thành công');
    } catch (error: any) {
      Alert.alert('Thất bại', error?.message || 'Mã OTP không hợp lệ');
    } finally {
      setLoading(false);
    }
  }

  async function resetPassword() {
    if (newPassword !== confirmPassword) {
      Alert.alert('Thất bại', 'Mật khẩu xác nhận không khớp');
      return;
    }
    setLoading(true);
    try {
      await api.resetPasswordWithCode(email, code, newPassword);
      Alert.alert('Thành công', 'Đã đặt lại mật khẩu');
      router.replace('/auth/login');
    } catch (error: any) {
      Alert.alert('Thất bại', error?.message || 'Không đặt lại được mật khẩu');
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={styles.root}>
      <NeonBackground />
      <View style={styles.wrap}>
        <GlassCard style={styles.card}>
          <Text style={styles.title}>Khôi phục mật khẩu</Text>
          <TextInput style={styles.input} placeholder="Email" placeholderTextColor={colors.textSoft} autoCapitalize="none" value={email} onChangeText={setEmail} />
          {step === 'send' ? (
            <Pressable style={styles.button} onPress={sendCode} disabled={loading || !email}>
              {loading ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.buttonText}>Gửi OTP</Text>}
            </Pressable>
          ) : null}
          {step === 'verify' ? (
            <>
              <TextInput style={styles.input} placeholder="Mã OTP" placeholderTextColor={colors.textSoft} value={code} onChangeText={setCode} />
              <Pressable style={styles.button} onPress={verifyCode} disabled={loading || !code}>
                {loading ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.buttonText}>Xác nhận mã</Text>}
              </Pressable>
            </>
          ) : (
            step === 'reset' ? (
              <>
              <TextInput style={styles.input} placeholder="Mã OTP" placeholderTextColor={colors.textSoft} value={code} onChangeText={setCode} />
              <TextInput style={styles.input} placeholder="Mật khẩu mới" placeholderTextColor={colors.textSoft} secureTextEntry value={newPassword} onChangeText={setNewPassword} />
              <TextInput style={styles.input} placeholder="Xác nhận mật khẩu mới" placeholderTextColor={colors.textSoft} secureTextEntry value={confirmPassword} onChangeText={setConfirmPassword} />
              <Pressable style={styles.button} onPress={resetPassword} disabled={loading || !newPassword || !confirmPassword || !code}>
                {loading ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.buttonText}>Đặt lại mật khẩu</Text>}
              </Pressable>
              </>
            ) : null
          )}
        </GlassCard>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg0 },
  wrap: { flex: 1, justifyContent: 'center', padding: 18 },
  card: { gap: 10 },
  title: { color: colors.text, fontSize: 24, fontWeight: '800', marginBottom: 4 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, color: colors.text, backgroundColor: 'rgba(255,255,255,0.92)', paddingHorizontal: 12, paddingVertical: 11 },
  button: { backgroundColor: colors.cyan, borderRadius: 12, minHeight: 46, alignItems: 'center', justifyContent: 'center' },
  buttonText: { color: '#ffffff', fontWeight: '800' },
});
