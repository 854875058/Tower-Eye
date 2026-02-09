/**
 * 主应用入口
 * 使用 Ant Design Pro Layout
 */
import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import ProLayout from '@ant-design/pro-layout';
import {
  DashboardOutlined,
  SearchOutlined,
  EnvironmentOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';

import SearchPage from './pages/SearchPage';
import MapPage from './pages/MapPage';
import DashboardPage from './pages/DashboardPage';
import './App.css';

const App = () => {
  const [pathname, setPathname] = useState('/search');

  // 菜单配置
  const menuData = [
    {
      path: '/dashboard',
      name: '数据大屏',
      icon: <DashboardOutlined />,
    },
    {
      path: '/search',
      name: '智能检索',
      icon: <SearchOutlined />,
    },
    {
      path: '/map',
      name: '地图展示',
      icon: <EnvironmentOutlined />,
    },
  ];

  return (
    <ConfigProvider locale={zhCN}>
      <Router>
        <ProLayout
          title="多模态检索系统"
          logo={<DashboardOutlined style={{ fontSize: 32 }} />}
          layout="mix"
          navTheme="light"
          primaryColor="#1677ff"
          fixedHeader
          fixSiderbar
          contentWidth="Fluid"
          route={{
            path: '/',
            routes: menuData,
          }}
          location={{
            pathname,
          }}
          menuItemRender={(item, dom) => (
            <a
              onClick={() => {
                setPathname(item.path || '/');
              }}
              href={item.path}
            >
              {dom}
            </a>
          )}
          headerContentRender={() => (
            <div style={{ padding: '0 16px' }}>
              <h2 style={{ margin: 0, color: '#1f1f1f' }}>
                统一多维数据底座
              </h2>
            </div>
          )}
          footerRender={() => (
            <div style={{ textAlign: 'center', padding: '16px' }}>
              多模态检索系统 © 2024 | 支持多模态、空间、时序的统一检索
            </div>
          )}
        >
          <Routes>
            <Route path="/" element={<Navigate to="/search" replace />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/map" element={<MapPage />} />
          </Routes>
        </ProLayout>
      </Router>
    </ConfigProvider>
  );
};

export default App;
