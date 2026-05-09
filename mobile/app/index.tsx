import { Redirect } from 'expo-router';
import { ActivityIndicator, SafeAreaView, StyleSheet } from 'react-native';

import { useSession } from '@/src/useSession';

export default function IndexScreen() {
  const session = useSession();

  if (!session.hydrated) {
    return (
      <SafeAreaView style={styles.root}>
        <ActivityIndicator size="large" color="#2563eb" />
      </SafeAreaView>
    );
  }

  if (!session.accessToken) {
    return <Redirect href="/auth/login" />;
  }

  return <Redirect href="/(tabs)" />;
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f8fafc',
  },
});
