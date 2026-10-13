import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';

// React管理首屏与导航；业务模块保留现有API、用户数据和独立会话。
createRoot(document.getElementById('app')).render(<App />);
