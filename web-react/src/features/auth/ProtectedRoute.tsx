import { useQuery } from '@tanstack/react-query';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { authApi } from '../../api/auth';
import { useAppStore } from '../../stores/appStore';

export function ProtectedRoute() {
  const location = useLocation();
  const setCurrentUser = useAppStore((state) => state.setCurrentUser);
  const currentUser = useAppStore((state) => state.currentUser);

  const query = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: async () => {
      const data = await authApi.me();
      setCurrentUser(data.user);
      return data.user;
    },
    retry: false,
  });

  if (query.isLoading && !currentUser) {
    return (
      <main className="auth-shell">
        <section className="auth-panel">
          <div className="auth-subtitle">读取登录状态…</div>
        </section>
      </main>
    );
  }

  if (query.isError && !currentUser) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
