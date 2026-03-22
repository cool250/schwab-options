import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Navbar from './components/Navbar'
import MarketData from './pages/MarketData'
import Positions from './pages/Positions'
import Transactions from './pages/Transactions'
import StockAllocation from './pages/StockAllocation'

export default function App() {
  return (
    <BrowserRouter>
      <Navbar />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Navigate to="/market" replace />} />
          <Route path="/market" element={<MarketData />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/allocation" element={<StockAllocation />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
