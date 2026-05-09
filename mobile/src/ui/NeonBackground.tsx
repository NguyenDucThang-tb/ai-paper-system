import { LinearGradient } from 'expo-linear-gradient';
import { StyleSheet, View } from 'react-native';

export default function NeonBackground() {
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <LinearGradient
        colors={['#f9fbff', '#eef4ff', '#f2ecff']}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={StyleSheet.absoluteFill}
      />
      <View style={styles.glowA} />
      <View style={styles.glowB} />
      <View style={styles.glowC} />
    </View>
  );
}

const styles = StyleSheet.create({
  glowA: {
    position: 'absolute',
    top: -80,
    right: -70,
    width: 240,
    height: 240,
    borderRadius: 999,
    backgroundColor: 'rgba(159,103,255,0.18)',
  },
  glowB: {
    position: 'absolute',
    bottom: 140,
    left: -60,
    width: 220,
    height: 220,
    borderRadius: 999,
    backgroundColor: 'rgba(14,165,233,0.14)',
  },
  glowC: {
    position: 'absolute',
    bottom: -110,
    right: 20,
    width: 280,
    height: 280,
    borderRadius: 999,
    backgroundColor: 'rgba(79,124,255,0.12)',
  },
});
