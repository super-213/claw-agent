import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactNode, useMemo, useEffect } from 'react';
import { useAppStore } from '../stores/appStore';
import { clearCardEdits } from '../features/interactive-cards/state';
import './cards';

export function AppProviders({ children }: { children: ReactNode }) {
  const owner = useAppStore(state => state.currentUser?.id);
  const queryClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
    [],
  );
  useEffect(() => {
    clearCardEdits();
    queryClient.removeQueries({ queryKey: ['interactive-cards'] });
    queryClient.removeQueries({ queryKey: ['board'] });
    queryClient.removeQueries({ queryKey: ['board-detail'] });
  }, [owner, queryClient]);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
