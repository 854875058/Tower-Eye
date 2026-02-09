/**
 * 智能检索页面
 * 支持多模态、空间、时序的联合检索
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  Form,
  Input,
  Select,
  DatePicker,
  Button,
  Row,
  Col,
  Space,
  Spin,
  Empty,
  message,
  Image,
  Tag,
  Statistic,
  Divider,
  InputNumber,
} from 'antd';
import {
  SearchOutlined,
  EnvironmentOutlined,
  ClockCircleOutlined,
  FileImageOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { search, getConfig, getMediaUrl } from '../services/api';
import './SearchPage.css';

const { RangePicker } = DatePicker;
const { Option } = Select;

const SearchPage = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [config, setConfig] = useState(null);
  const [searchStats, setSearchStats] = useState({
    total: 0,
    queryTime: 0,
  });

  // 加载配置
  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      const res = await getConfig();
      if (res.success) {
        setConfig(res.config);
      }
    } catch (error) {
      message.error('加载配置失败');
    }
  };

  // 执行检索
  const handleSearch = async (values) => {
    setLoading(true);
    const startTime = Date.now();

    try {
      // 构建检索参数
      const params = {
        text: values.text || null,
        event_type: values.event_type || null,
        start_time: values.time_range?.[0]?.format('YYYY-MM-DD HH:mm:ss') || null,
        end_time: values.time_range?.[1]?.format('YYYY-MM-DD HH:mm:ss') || null,
        lat: values.lat || null,
        lon: values.lon || null,
        radius_km: values.radius_km || 5.0,
        top_k: values.top_k || 20,
        hybrid: values.hybrid || false,
      };

      const res = await search(params);

      if (res.success) {
        setResults(res.results);
        setSearchStats({
          total: res.total,
          queryTime: Date.now() - startTime,
        });
        message.success(`检索成功，找到 ${res.total} 条结果`);
      }
    } catch (error) {
      message.error('检索失败：' + error.message);
    } finally {
      setLoading(false);
    }
  };

  // 重置表单
  const handleReset = () => {
    form.resetFields();
    setResults([]);
    setSearchStats({ total: 0, queryTime: 0 });
  };

  // 渲染结果卡片
  const renderResultCard = (item, index) => {
    const isImage = item.media_type === 'image';
    const isVideo = item.media_type === 'video';

    return (
      <Card
        key={item.asset_id || index}
        hoverable
        className="result-card"
        cover={
          isImage ? (
            <Image
              alt={item.summary || '图片'}
              src={getMediaUrl(item.asset_id)}
              height={200}
              style={{ objectFit: 'cover' }}
              placeholder={
                <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Spin />
                </div>
              }
            />
          ) : isVideo ? (
            <div style={{ height: 200, background: '#f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <VideoCameraOutlined style={{ fontSize: 48, color: '#999' }} />
            </div>
          ) : null
        }
      >
        <Card.Meta
          title={
            <Space>
              <Tag color="blue">{item.event_type || '未知类型'}</Tag>
              {item.distance && (
                <Tag color="green">相似度: {(1 - item.distance).toFixed(3)}</Tag>
              )}
            </Space>
          }
          description={
            <div>
              <p className="result-summary">{item.summary || '暂无描述'}</p>
              <Divider style={{ margin: '8px 0' }} />
              <Space direction="vertical" size="small" style={{ width: '100%' }}>
                {item.alarm_time && (
                  <div>
                    <ClockCircleOutlined /> {item.alarm_time}
                  </div>
                )}
                {item.region && (
                  <div>
                    <EnvironmentOutlined /> {item.region}
                  </div>
                )}
                {item.lat && item.lon && (
                  <div style={{ fontSize: 12, color: '#999' }}>
                    坐标: ({item.lat.toFixed(4)}, {item.lon.toFixed(4)})
                  </div>
                )}
              </Space>
            </div>
          }
        />
      </Card>
    );
  };

  return (
    <div className="search-page">
      {/* 搜索表单 */}
      <Card title="智能检索" className="search-form-card">
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSearch}
          initialValues={{
            top_k: 20,
            radius_km: 5.0,
            hybrid: false,
          }}
        >
          <Row gutter={16}>
            {/* 文本检索 */}
            <Col xs={24} sm={24} md={12} lg={8}>
              <Form.Item
                label="检索内容"
                name="text"
                tooltip="输入关键词进行多模态检索"
              >
                <Input
                  placeholder="例如：夜间烟火、车辆闯入"
                  prefix={<SearchOutlined />}
                  size="large"
                />
              </Form.Item>
            </Col>

            {/* 事件类型 */}
            <Col xs={24} sm={12} md={12} lg={8}>
              <Form.Item
                label="事件类型"
                name="event_type"
              >
                <Select
                  placeholder="选择事件类型"
                  allowClear
                  size="large"
                >
                  {config?.event_types?.map((type) => (
                    <Option key={type} value={type}>
                      {type}
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>

            {/* 时间范围 */}
            <Col xs={24} sm={12} md={12} lg={8}>
              <Form.Item
                label="时间范围"
                name="time_range"
              >
                <RangePicker
                  showTime
                  format="YYYY-MM-DD HH:mm"
                  placeholder={['开始时间', '结束时间']}
                  style={{ width: '100%' }}
                  size="large"
                />
              </Form.Item>
            </Col>

            {/* 地理位置 - 纬度 */}
            <Col xs={24} sm={12} md={8} lg={6}>
              <Form.Item
                label="纬度"
                name="lat"
                tooltip="输入纬度坐标"
              >
                <InputNumber
                  placeholder="例如：39.9"
                  style={{ width: '100%' }}
                  min={-90}
                  max={90}
                  step={0.0001}
                  size="large"
                />
              </Form.Item>
            </Col>

            {/* 地理位置 - 经度 */}
            <Col xs={24} sm={12} md={8} lg={6}>
              <Form.Item
                label="经度"
                name="lon"
                tooltip="输入经度坐标"
              >
                <InputNumber
                  placeholder="例如：116.4"
                  style={{ width: '100%' }}
                  min={-180}
                  max={180}
                  step={0.0001}
                  size="large"
                />
              </Form.Item>
            </Col>

            {/* 搜索半径 */}
            <Col xs={24} sm={12} md={8} lg={6}>
              <Form.Item
                label="搜索半径（公里）"
                name="radius_km"
              >
                <InputNumber
                  placeholder="5.0"
                  style={{ width: '100%' }}
                  min={0.1}
                  max={1000}
                  step={0.1}
                  size="large"
                />
              </Form.Item>
            </Col>

            {/* 返回数量 */}
            <Col xs={24} sm={12} md={8} lg={6}>
              <Form.Item
                label="返回数量"
                name="top_k"
              >
                <InputNumber
                  placeholder="20"
                  style={{ width: '100%' }}
                  min={1}
                  max={100}
                  size="large"
                />
              </Form.Item>
            </Col>
          </Row>

          {/* 操作按钮 */}
          <Row>
            <Col span={24}>
              <Space>
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<SearchOutlined />}
                  size="large"
                  loading={loading}
                >
                  开始检索
                </Button>
                <Button
                  onClick={handleReset}
                  size="large"
                >
                  重置
                </Button>
              </Space>
            </Col>
          </Row>
        </Form>
      </Card>

      {/* 检索统计 */}
      {searchStats.total > 0 && (
        <Card className="stats-card">
          <Row gutter={16}>
            <Col span={12}>
              <Statistic
                title="检索结果"
                value={searchStats.total}
                suffix="条"
              />
            </Col>
            <Col span={12}>
              <Statistic
                title="查询耗时"
                value={searchStats.queryTime}
                suffix="ms"
              />
            </Col>
          </Row>
        </Card>
      )}

      {/* 检索结果 */}
      <Card title={`检索结果 (${results.length})`} className="results-card">
        <Spin spinning={loading}>
          {results.length > 0 ? (
            <Row gutter={[16, 16]}>
              {results.map((item, index) => (
                <Col xs={24} sm={12} md={8} lg={6} key={item.asset_id || index}>
                  {renderResultCard(item, index)}
                </Col>
              ))}
            </Row>
          ) : (
            <Empty
              description="暂无检索结果"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          )}
        </Spin>
      </Card>
    </div>
  );
};

export default SearchPage;
