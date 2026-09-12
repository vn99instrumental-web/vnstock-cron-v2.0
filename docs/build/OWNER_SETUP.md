# OWNER_SETUP — Hướng dẫn cấu hình cho owner (người không chuyên)

> Làm theo thứ tự. Mỗi bước có: **làm gì · click ở đâu · cách kiểm tra đúng chưa**.
> Toàn bộ ~30–45 phút. Không cần biết code.

**Có 3 nhóm việc:**
- **Nhóm A — Cho data chảy lên bảng** (bắt buộc, làm trước).
- **Nhóm B — Đưa web lên mạng** (Vercel) + tạo tài khoản đăng nhập.
- **Nhóm C — Bật nút Promote** (chỉnh cấu hình chấm điểm từ web).

⚠️ **2 "chìa khóa bí mật"** anh sẽ lấy: **Supabase secret key** và **GitHub token**.
Chúng có quyền rất cao — **không gửi cho ai, không dán vào chat, không chụp màn hình chia sẻ**.
Chỉ dán vào đúng ô "Secret" của GitHub/Vercel như hướng dẫn.

---

## 🔑 Bước 0 — Lấy 2 chìa khóa bí mật (làm 1 lần, dùng cho các bước sau)

### 0.1. Supabase "secret key" (service role)
1. Vào **https://supabase.com** → **Sign in** (đăng nhập bằng email `vn99instrumental@gmail.com`).
2. Chọn project **"vn99instrumental@gmail.com's Project"**.
3. Góc dưới trái, bấm biểu tượng **⚙️ Project Settings** → chọn mục **API Keys** (hoặc **API**).
4. Tìm khu vực khóa bí mật:
   - Nếu thấy **"Secret keys"** → bấm **Reveal / Copy** dòng bắt đầu bằng `sb_secret_...`
   - Hoặc nếu thấy **"service_role"** (khóa cũ, chuỗi dài `eyJ...`) → **Reveal / Copy** dòng đó.
   - (Cả hai đều dùng được — đây là "chìa khóa quyền cao".)
5. **Dán tạm vào Notepad** (lát nữa dùng). ⚠️ Đây là khóa bí mật.

> Ghi chú: **Project URL** (dạng `https://mcaqnaomzoqgxccdgvls.supabase.co`) nằm cùng trang này — không bí mật, đã có sẵn trong code.

### 0.2. GitHub token (để nút Promote ghi được cấu hình)
> Bước này có thể làm sau, chỉ cần cho **Nhóm C**. Nếu chưa dùng Promote thì bỏ qua.
1. Vào **https://github.com** → đăng nhập tài khoản **vn99instrumental-web**.
2. Bấm **avatar góc phải trên** → **Settings**.
3. Cuộn xuống menu trái, bấm **Developer settings** (dưới cùng).
4. **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
5. Điền:
   - **Token name:** `vnstock-promote`
   - **Expiration:** chọn 90 ngày (hoặc Custom xa hơn).
   - **Resource owner:** `vn99instrumental-web`
   - **Repository access:** chọn **Only select repositories** → tick **`vnstock-cron-v2.0`**.
   - **Permissions** → mở **Repository permissions** → tìm **Contents** → chọn **Read and write**.
     (Mục **Metadata** sẽ tự bật Read — kệ nó.)
6. Bấm **Generate token** → **Copy** chuỗi `github_pat_...` → dán tạm vào Notepad. ⚠️ Bí mật.

---

## 🟢 Nhóm A — Cho data chảy lên bảng (bắt buộc)

### A.1. Dán Supabase key vào GitHub (để robot tự đồng bộ data)
1. Vào **https://github.com/vn99instrumental-web/vnstock-cron-v2.0**.
2. Bấm tab **Settings** (của repo, không phải của tài khoản).
3. Menu trái: **Secrets and variables** → **Actions**.
4. Bấm **New repository secret**.
5. Điền:
   - **Name:** `SUPABASE_SERVICE_ROLE_KEY` (gõ chính xác, IN HOA, có dấu gạch dưới)
   - **Secret:** dán khóa bí mật Supabase ở bước 0.1.
6. Bấm **Add secret**.

✅ **Kiểm tra:** thấy dòng `SUPABASE_SERVICE_ROLE_KEY` xuất hiện trong danh sách secrets.

### A.2. Gộp code vào nhánh chính (main)
> Code đang nằm ở nhánh `claude/bold-pascal-768taz`. Cần gộp vào `main` để robot chạy.
1. Vào repo → tab **Pull requests** → **New pull request**.
2. Chọn: **base = `main`**, **compare = `claude/bold-pascal-768taz`**.
3. Bấm **Create pull request** → (đặt tiêu đề bất kỳ) → **Create pull request** lần nữa.
4. Bấm **Merge pull request** → **Confirm merge**.

✅ **Kiểm tra:** vào tab **Code**, chọn nhánh **main**, thấy có thư mục `web/`, `config/`, và file `scripts/sync_supabase.py`.

### A.3. Chờ data tự lên (không phải làm gì)
- Pipeline chạy tự động **5 lần/ngày** (do n8n). Lần chạy kế tiếp trong giờ giao dịch sẽ tự đẩy data lên bảng.
- Muốn **chạy ngay** không chờ: vào repo → tab **Actions** → chọn workflow **"VNStock Intraday V2F"** → **Run workflow** → **Run**.

✅ **Kiểm tra data đã lên:** vào **Supabase → Table Editor →** bảng **`v4_signals`** → thấy có dòng dữ liệu (thay vì 0 rows).

---

## 🔵 Nhóm B — Đưa web lên mạng (Vercel) + tạo tài khoản đăng nhập

### B.1. Import dự án vào Vercel
1. Vào **https://vercel.com** → **Sign up / Log in** → chọn **Continue with GitHub**.
2. **Add New…** → **Project** → tìm repo **`vnstock-cron-v2.0`** → **Import**.
3. ⚠️ **QUAN TRỌNG:** ở mục **Root Directory**, bấm **Edit** → chọn thư mục **`web`**.
   (Vì app nằm trong thư mục con `web/`. Bỏ qua bước này web sẽ build lỗi.)
4. Framework Preset sẽ tự nhận **Next.js**.

### B.2. Điền biến môi trường (Environment Variables) trên Vercel
Trong màn hình import (hoặc sau này ở **Project → Settings → Environment Variables**), thêm từng dòng:

| Name (Key) | Value | Bí mật? |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://mcaqnaomzoqgxccdgvls.supabase.co` | Không |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `sb_publishable_kUJoHfwJAM-dZY76a3W-4A_HGSzEuJA` | Không |
| `NEXT_PUBLIC_OWNER_EMAIL` | `vn99instrumental@gmail.com` | Không |
| `SUPABASE_URL` | `https://mcaqnaomzoqgxccdgvls.supabase.co` | Không |
| `SUPABASE_SERVICE_ROLE_KEY` | (khóa bí mật Supabase — bước 0.1) | **CÓ** |
| `GITHUB_TOKEN` | (token GitHub — bước 0.2) | **CÓ** |
| `GITHUB_REPO` | `vn99instrumental-web/vnstock-cron-v2.0` | Không |
| `CONFIG_PATH` | `config/scoring/active.json` | Không |

> Nếu chưa làm bước 0.2 (chưa cần Promote), có thể tạm bỏ `GITHUB_TOKEN` và `SUPABASE_SERVICE_ROLE_KEY` — web vẫn xem được tín hiệu, chỉ chưa Promote được.

### B.3. Deploy
1. Bấm **Deploy**. Chờ ~1–2 phút.
2. Xong, Vercel cho 1 link dạng `https://...vercel.app`.

✅ **Kiểm tra:** mở link → thấy trang **Hôm nay**. Nếu data đã lên (Nhóm A) sẽ thấy bảng tín hiệu; nếu chưa, thấy "Chưa có dữ liệu" (bình thường).

### B.4. Tạo tài khoản đăng nhập owner (để vào /config)
1. Vào **Supabase → Authentication → Users → Add user → Create new user**.
2. Điền:
   - **Email:** `vn99instrumental@gmail.com`
   - **Password:** đặt mật khẩu mạnh (nhớ kỹ).
   - Tick **Auto Confirm User** (để dùng được ngay, khỏi xác nhận email).
3. Bấm **Create user**.
4. (Khuyến nghị) **Authentication → Providers/Sign In → Email:** tắt **"Allow new users to sign up"** — để không ai tự đăng ký thêm (chỉ mình anh).

✅ **Kiểm tra:** mở web → bấm **Đăng nhập** → nhập email + mật khẩu vừa tạo → thấy menu **Cấu hình** hiện ra.

---

## 🟣 Nhóm C — Bật nút Promote (chỉnh cấu hình chấm điểm)

Chỉ cần đảm bảo **đã có** `GITHUB_TOKEN` + `SUPABASE_SERVICE_ROLE_KEY` trong Vercel (bước B.2)
và **đã tạo tài khoản owner** (B.4). Không cần thao tác thêm.

✅ **Kiểm tra:** đăng nhập web → vào **Cấu hình** → chỉnh 1 trọng số → bấm **Promote** → thấy "✅ Promote thành công".
Sau đó vào repo GitHub → file `config/scoring/active.json` sẽ có nội dung mới.

---

## (Tùy chọn) Chạy thử trên máy trước khi deploy
1. Cài **Node.js 20+** tại **https://nodejs.org** (bản LTS).
2. Mở **Terminal / Command Prompt**, di chuyển vào thư mục `web` của dự án.
3. Gõ lần lượt:
   ```
   cp .env.local.example .env.local
   ```
   Mở file `.env.local`, điền `NEXT_PUBLIC_OWNER_EMAIL` và (nếu test Promote) `SUPABASE_SERVICE_ROLE_KEY`, `GITHUB_TOKEN`.
   ```
   npm install
   npm run dev
   ```
4. Mở trình duyệt **http://localhost:3000**.

---

## Bảng tóm tắt (checklist)

- [ ] 0.1 Lấy Supabase secret key
- [ ] 0.2 Tạo GitHub token (nếu dùng Promote)
- [ ] A.1 Dán secret vào GitHub Actions (`SUPABASE_SERVICE_ROLE_KEY`)
- [ ] A.2 Merge nhánh → `main`
- [ ] A.3 Chờ / bấm chạy workflow → data lên bảng
- [ ] B.1 Import repo vào Vercel, **Root = `web`**
- [ ] B.2 Điền 8 biến môi trường
- [ ] B.3 Deploy
- [ ] B.4 Tạo user owner trong Supabase Auth
- [ ] C  Test Promote

---

## Nếu gặp lỗi (thường gặp)
- **Web build lỗi trên Vercel** → 90% do quên đặt **Root Directory = `web`** (bước B.1).
- **Vào /config bị đá về trang đăng nhập** → chưa tạo user owner (B.4), hoặc email đăng nhập khác `NEXT_PUBLIC_OWNER_EMAIL`.
- **Promote báo "Server chưa cấu hình…"** → thiếu `GITHUB_TOKEN` hoặc `SUPABASE_SERVICE_ROLE_KEY` trong Vercel (B.2) → thêm rồi **Redeploy**.
- **Bảng vẫn 0 rows sau khi merge** → chưa tới giờ pipeline chạy; bấm chạy tay ở tab **Actions** (A.3), hoặc kiểm secret `SUPABASE_SERVICE_ROLE_KEY` gõ có đúng tên không.
