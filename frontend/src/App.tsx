import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MainLayout from './components/Layout/MainLayout';
import DashboardPage from './pages/DashboardPage';
import KeywordPage from './pages/KeywordPage';
import InsightsPage from './pages/InsightsPage';
import ImagePage from './pages/ImagePage';
import RelatedBulkPage from './pages/RelatedBulkPage';
import MarginPage from './pages/MarginPage';
import RecommendProductsPage from './pages/RecommendProductsPage';
import ReviewPage from './pages/ReviewPage';
import ShopBenchmarkPage from './pages/ShopBenchmarkPage';
import SettingsPage from './pages/SettingsPage';
import BlacklistPage from './pages/BlacklistPage';

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/keywords" element={<KeywordPage />} />
            <Route path="/insights" element={<InsightsPage />} />
            <Route path="/image" element={<ImagePage />} />
            <Route path="/related-bulk" element={<RelatedBulkPage />} />
            <Route path="/margin" element={<MarginPage />} />
            <Route path="/recommend-products" element={<RecommendProductsPage />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="/review/:date" element={<ReviewPage />} />
            <Route path="/shop-benchmark" element={<ShopBenchmarkPage />} />
            <Route path="/blacklist" element={<BlacklistPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
