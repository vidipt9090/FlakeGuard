import { Route, Routes } from 'react-router-dom';
import BotText from './pages/BotText';
import Findings from './pages/Findings';
import Live from './pages/Live';
import NoTests from './pages/NoTests';
import RepoMap from './pages/RepoMap';
import Results from './pages/Results';
import States from './pages/States';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Live />} />
      <Route path="/findings" element={<Findings />} />
      <Route path="/repo-map" element={<RepoMap />} />
      <Route path="/results" element={<Results />} />
      <Route path="/no-tests" element={<NoTests />} />
      <Route path="/states" element={<States />} />
      <Route path="/bot-text" element={<BotText />} />
    </Routes>
  );
}
