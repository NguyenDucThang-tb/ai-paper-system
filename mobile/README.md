# AI Paper Mobile (Expo)

Ung dung mobile/web cho `ai-paper-system`, ket noi truc tiep backend FastAPI.

## Chuc nang hien tai (dong bo theo frontend)

- Auth: login, register, forgot-password
- Home: workspace/notebook list, tao workspace
- Library: danh sach tai lieu, mo chi tiet
- Document detail: summary, QA, recommendations, timeline, xoa tai lieu
- Search: CMS search
- Upload: upload PDF, gan vao workspace tuy chon
- Profile: xem/cap nhat user, doi mat khau, dang xuat
- Analytics: analytics + cms dashboard + admin users (neu co quyen)

## Cai dat

```bash
cd mobile
npm install
```

## Cau hinh backend URL

Tao file `.env` (hoac `.env.local`) trong thu muc `mobile`:

```env
EXPO_PUBLIC_API_BASE_URL=https://triumphant-charisma-production-f2a9.up.railway.app/api/v1
```

Neu dung Android emulator:

```env
EXPO_PUBLIC_API_BASE_URL=https://triumphant-charisma-production-f2a9.up.railway.app/api/v1
```

Neu dung dien thoai that (cung Wi-Fi voi backend):

```env
EXPO_PUBLIC_API_BASE_URL=https://triumphant-charisma-production-f2a9.up.railway.app/api/v1
```

## Chay

```bash
npm run start
```

- `a`: mo Android emulator
- `w`: mo Web
- Expo Go: quet QR code

Neu web bi cache loi cu:

```bash
npm run start -- --clear
```
