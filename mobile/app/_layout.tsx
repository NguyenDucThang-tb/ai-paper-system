import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

export default function RootLayout() {
  return (
    <>
      <Stack>
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="auth/login" options={{ title: 'Đăng nhập' }} />
        <Stack.Screen name="auth/register" options={{ title: 'Đăng ký' }} />
        <Stack.Screen name="auth/forgot-password" options={{ title: 'Quên mật khẩu' }} />
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="workspace/[id]" options={{ title: 'Chi tiết workspace' }} />
        <Stack.Screen name="document/[id]" options={{ title: 'Chi tiết tài liệu' }} />
      </Stack>
      <StatusBar style="light" />
    </>
  );
}
