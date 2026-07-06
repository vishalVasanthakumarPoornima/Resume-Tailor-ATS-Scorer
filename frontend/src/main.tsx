import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// No StrictMode: its dev-only double-mount interrupts GSAP entrance animations
// (React Bits SplitText) mid-flight, leaving text half-faded.
createRoot(document.getElementById('root')!).render(<App />)
