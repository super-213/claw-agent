import { useEffect } from 'react';
import { useRoutes } from 'react-router-dom';
import { routes } from './router';

export function App() {
  const element = useRoutes(routes);

  useEffect(() => {
    const onUnauthorized = () => {
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    };
    window.addEventListener('claw-api-unauthorized', onUnauthorized);
    return () => window.removeEventListener('claw-api-unauthorized', onUnauthorized);
  }, []);

  return <div className="react-route-shell">{element}</div>;
}
