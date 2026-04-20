import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MainLayout from './components/Layout/MainLayout';
import DashboardPage from './pages/DashboardPage';
import KeywordPage from './pages/KeywordPage';
import RecommendPage from './pages/RecommendPage';
import InsightsPage from './pages/InsightsPage';
import ImagePage from './pages/ImagePage';
import PriceComparePage from './pages/PriceComparePage';
import RelatedBulkPage from './pages/RelatedBulkPage';
import CompetitionPage from './pages/CompetitionPage';
import BidPage from './pages/BidPage';
import ProductSearchPage from './pages/ProductSearchPage';
import TrackingPage from './pages/TrackingPage';
import BestsellerPage from './pages/BestsellerPage';
import MarginPage from './pages/MarginPage';
import RecommendProductsPage from './pages/RecommendProductsPage';

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/keywords" element={<KeywordPage />} />
            <Route path="/recommend" element={<RecommendPage />} />
            <Route path="/insights" element={<InsightsPage />} />
            <Route path="/image" element={<ImagePage />} />
            <Route path="/price-compare" element={<PriceComparePage />} />
            <Route path="/related-bulk" element={<RelatedBulkPage />} />
            <Route path="/competition" element={<CompetitionPage />} />
            <Route path="/bid" element={<BidPage />} />
            <Route path="/products" element={<ProductSearchPage />} />
            <Route path="/tracking" element={<TrackingPage />} />
            <Route path="/bestsellers" element={<BestsellerPage />} />
            <Route path="/margin" element={<MarginPage />} />
            <Route path="/recommend-products" element={<RecommendProductsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
