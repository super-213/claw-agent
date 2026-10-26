import { Navigate, RouteObject } from 'react-router-dom';
import { ProtectedRoute } from '../features/auth/ProtectedRoute';
import { LoginPage } from '../features/auth/LoginPage';
import { ChatWorkspace } from '../features/chat/ChatWorkspace';
import { DashboardPage } from '../features/dashboard/DashboardPage';
import { HomePage } from '../features/home/HomePage';

export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <HomePage />,
        children: [
          { path: '/', element: null },
          { path: '/home', element: null },
          { path: '/home/items', element: null },
          { path: '/home/tasks', element: null },
          { path: '/home/more', element: null },
          { path: '/home/reminders/:reminderId', element: null },
        ],
      },
      { path: '/chat', element: <ChatWorkspace /> },
      { path: '/sessions/:sessionId', element: <ChatWorkspace /> },
      {
        path: '/sessions/:sessionId/tree',
        element: <ChatWorkspace initialTreeOpen />,
      },
      { path: '/dashboard', element: <DashboardPage /> },
      { path: '/settings', element: <ChatWorkspace initialModal="settings" /> },
      { path: '/plugins', element: <ChatWorkspace initialModal="plugins" /> },
      { path: '/admin/users', element: <ChatWorkspace initialModal="users" /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
];
