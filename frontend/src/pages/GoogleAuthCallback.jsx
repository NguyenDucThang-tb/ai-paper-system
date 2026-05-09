import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "@/lib/api";

function readHashParams() {
  const raw = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "";
  return new URLSearchParams(raw);
}

export default function GoogleAuthCallbackPage() {
  const navigate = useNavigate();
  const [message, setMessage] = useState("Đang hoàn tất đăng nhập Google...");

  useEffect(() => {
    let active = true;

    async function completeGoogleAuth() {
      const params = readHashParams();
      const error = params.get("error");
      const errorDescription = params.get("error_description");
      const accessToken = params.get("access_token");
      const refreshToken = params.get("refresh_token");

      if (error) {
        if (active) {
          setMessage(
            errorDescription
              ? `Đăng nhập Google thất bại: ${errorDescription}`
              : "Đăng nhập Google thất bại."
          );
        }
        window.setTimeout(() => navigate("/login"), 1200);
        return;
      }

      if (!accessToken || !refreshToken) {
        if (active) setMessage("Thiếu thông tin phiên đăng nhập từ Google.");
        window.setTimeout(() => navigate("/login"), 1200);
        return;
      }

      try {
        api.saveTokenPair(accessToken, refreshToken);
        const user = await api.me();
        localStorage.setItem("current_user", JSON.stringify(user));
        navigate(user.role === "admin" ? "/admin" : "/home");
      } catch {
        api.clearSession();
        if (active) setMessage("Không thể hoàn tất phiên đăng nhập Google.");
        window.setTimeout(() => navigate("/login"), 1200);
      }
    }

    completeGoogleAuth();

    return () => {
      active = false;
    };
  }, [navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#08111c] px-6 text-white">
      <div className="rounded-3xl border border-white/10 bg-white/5 px-8 py-6 text-center text-sm backdrop-blur-sm">
        {message}
      </div>
    </div>
  );
}
