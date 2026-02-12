#!/bin/bash
# 重新入库脚本 - 清理并重新生成所有数据和索引
# 使用方法:
#   bash 重新入库.sh              # 完整重新入库
#   bash 重新入库.sh --skip-ingest  # 跳过数据导入，只重新生成向量
#   bash 重新入库.sh --quick        # 快速模式（跳过数据导入）
#   bash 重新入库.sh --incremental  # 增量模式（只处理新增图片，不清空已有向量）

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 获取脚本所在目录
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# 解析命令行参数
SKIP_INGEST=false
QUICK_MODE=false
INCREMENTAL=false

for arg in "$@"; do
    case $arg in
        --skip-ingest)
            SKIP_INGEST=true
            shift
            ;;
        --quick)
            QUICK_MODE=true
            SKIP_INGEST=true
            shift
            ;;
        --incremental)
            INCREMENTAL=true
            SKIP_INGEST=true
            shift
            ;;
        --already-activated)
            # 内部标志，跳过
            shift
            ;;
        --help|-h)
            echo "重新入库脚本 - 使用说明"
            echo ""
            echo "用法:"
            echo "  bash 重新入库.sh              # 完整重新入库（清理+导入+向量化）"
            echo "  bash 重新入库.sh --skip-ingest  # 跳过数据导入，只重新生成向量"
            echo "  bash 重新入库.sh --quick        # 快速模式（同 --skip-ingest）"
            echo "  bash 重新入库.sh --incremental  # 增量模式（只处理新增图片，不清空已有向量）"
            echo ""
            echo "说明:"
            echo "  - 完整模式：清理所有数据，重新导入，重新生成向量（耗时较长）"
            echo "  - 快速模式：保留数据库，只重新生成向量（适合切换模型后使用）"
            echo "  - 增量模式：保留已有向量，只处理新增图片（最快，适合日常更新）"
            exit 0
            ;;
    esac
done

# 查找并初始化 conda
CONDA_SH=""
if [ -f "/root/miniconda3/etc/profile.d/conda.sh" ]; then
    CONDA_SH="/root/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    CONDA_SH="$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    CONDA_SH="$HOME/anaconda3/etc/profile.d/conda.sh"
fi

# 如果找到了 conda.sh 并且不在 multimodal 环境中，则重新执行脚本
if [ -n "$CONDA_SH" ] && [ "${CONDA_DEFAULT_ENV:-}" != "multimodal" ]; then
    echo -e "${YELLOW}检测到当前环境: ${CONDA_DEFAULT_ENV:-none}${NC}"
    echo -e "${BLUE}正在切换到 multimodal 环境并重新执行脚本...${NC}"
    # 在新的 bash 中 source conda.sh，激活环境，然后执行脚本
    exec bash -c "source '$CONDA_SH' && conda activate multimodal && exec bash '$0' $* --already-activated"
fi

# 检查是否成功激活
if [ "${CONDA_DEFAULT_ENV:-}" != "multimodal" ]; then
    echo -e "${RED}✗ 错误: 无法自动切换到 multimodal 环境${NC}"
    echo "请手动运行: conda activate multimodal && bash 重新入库.sh"
    exit 1
fi

echo -e "${GREEN}✓ 当前环境: $CONDA_DEFAULT_ENV${NC}"
echo -e "${GREEN}✓ Python 路径: $(which python)${NC}"
echo ""

# 显示模式
if [ "$INCREMENTAL" = true ]; then
    echo -e "${BLUE}=== 增量入库模式（只处理新增图片）===${NC}"
elif [ "$QUICK_MODE" = true ]; then
    echo -e "${BLUE}=== 快速重新入库模式（仅重新生成向量）===${NC}"
elif [ "$SKIP_INGEST" = true ]; then
    echo -e "${BLUE}=== 跳过数据导入模式 ===${NC}"
else
    echo -e "${BLUE}=== 完整重新入库模式 ===${NC}"
fi
echo ""

# 记录开始时间
START_TIME=$(date +%s)

# 步骤计数
TOTAL_STEPS=2
if [ "$SKIP_INGEST" = false ]; then
    TOTAL_STEPS=4
fi
CURRENT_STEP=0

# 1. 清理旧数据（如果不是快速模式）
if [ "$SKIP_INGEST" = false ]; then
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo -e "${YELLOW}步骤 $CURRENT_STEP/$TOTAL_STEPS: 清理旧数据...${NC}"

    # 备份旧数据（可选）
    if [ -d "poc/data/lancedb" ] && [ "$(ls -A poc/data/lancedb 2>/dev/null)" ]; then
        BACKUP_DIR="poc/data/backup_$(date +%Y%m%d_%H%M%S)"
        echo "  创建备份: $BACKUP_DIR"
        mkdir -p "$BACKUP_DIR"
        [ -d "poc/data/lancedb" ] && cp -r poc/data/lancedb "$BACKUP_DIR/" 2>/dev/null || true
        [ -f "poc/data/metadata.db" ] && cp poc/data/metadata.db "$BACKUP_DIR/" 2>/dev/null || true
    fi

    rm -rf poc/data/lancedb/*
    rm -f poc/data/metadata.db
    echo -e "${GREEN}✓ 清理完成${NC}"
    echo ""
else
    echo -e "${YELLOW}跳过清理步骤（保留现有数据库）${NC}"
    echo ""
fi

# 2. 重新创建数据库结构（如果不是快速模式）
if [ "$SKIP_INGEST" = false ]; then
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo -e "${YELLOW}步骤 $CURRENT_STEP/$TOTAL_STEPS: 创建数据库结构...${NC}"
    python -m poc.pipeline.ingest --config poc/config/poc.yaml
    echo -e "${GREEN}✓ 数据库结构创建完成${NC}"
    echo ""
fi

# 3. 导入告警数据（如果不是快速模式）
if [ "$SKIP_INGEST" = false ]; then
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo -e "${YELLOW}步骤 $CURRENT_STEP/$TOTAL_STEPS: 导入告警数据（包含图像理解字段）...${NC}"
    python import_warning_data.py
    echo -e "${GREEN}✓ 告警数据导入完成${NC}"
    echo ""
fi

# 4. 清理旧向量数据（增量模式跳过）
if [ "$INCREMENTAL" = true ]; then
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo -e "${YELLOW}步骤 $CURRENT_STEP/$TOTAL_STEPS: 保留已有向量数据（增量模式）${NC}"
    echo ""
else
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo -e "${YELLOW}步骤 $CURRENT_STEP/$TOTAL_STEPS: 清理旧向量数据...${NC}"
    rm -rf poc/data/lancedb/*
    echo -e "${GREEN}✓ 向量数据清理完成${NC}"
    echo ""
fi

# 5. 生成向量嵌入并写入 LanceDB
CURRENT_STEP=$((CURRENT_STEP + 1))
echo -e "${YELLOW}步骤 $CURRENT_STEP/$TOTAL_STEPS: 生成向量嵌入并写入 LanceDB...${NC}"
echo -e "${BLUE}提示: 这可能需要几分钟，请耐心等待...${NC}"

# 显示当前配置
echo ""
echo "当前配置:"
python -c "
import yaml
with open('poc/config/poc.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
    search_cfg = config.get('search', {})
    model_type = search_cfg.get('embedding_model', 'clip')
    print(f'  - 模型类型: {model_type}')
    if model_type == 'qwen':
        print(f'  - API 地址: {search_cfg.get(\"qwen_api_url\", \"未配置\")}')
        print(f'  - Reranker: {\"启用\" if search_cfg.get(\"reranker_enabled\") else \"禁用\"}')
    else:
        print(f'  - CLIP 模型: {search_cfg.get(\"clip_model\", \"未配置\")}')
"
echo ""

# 执行向量化
EMBED_START=$(date +%s)
if [ "$INCREMENTAL" = true ]; then
    python -m poc.pipeline.embed --config poc/config/poc.yaml --incremental
else
    python -m poc.pipeline.embed --config poc/config/poc.yaml
fi
EMBED_END=$(date +%s)
EMBED_TIME=$((EMBED_END - EMBED_START))

echo -e "${GREEN}✓ 向量嵌入完成（耗时: ${EMBED_TIME}秒）${NC}"
echo ""

# 计算总耗时
END_TIME=$(date +%s)
TOTAL_TIME=$((END_TIME - START_TIME))

echo -e "${GREEN}=== 重新入库完成 ===${NC}"
echo -e "${BLUE}总耗时: ${TOTAL_TIME}秒 ($(($TOTAL_TIME / 60))分$(($TOTAL_TIME % 60))秒)${NC}"
echo ""

# 显示数据统计
echo "数据统计："
python -c "
import sqlite3
import os

db_path = 'poc/data/metadata.db'
if not os.path.exists(db_path):
    print('  ⚠ 数据库文件不存在')
    exit(0)

try:
    conn = sqlite3.connect(db_path)
    assets_count = conn.execute('SELECT COUNT(*) FROM assets').fetchone()[0]
    events_count = conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    summary_count = conn.execute('SELECT COUNT(*) FROM events WHERE summary IS NOT NULL AND summary != \"\"').fetchone()[0]

    print(f'  - Assets: {assets_count}')
    print(f'  - Events: {events_count}')
    print(f'  - 包含图像理解: {summary_count}')

    # 检查 LanceDB
    import lancedb
    try:
        db = lancedb.connect('poc/data/lancedb')
        if 'embeddings' in db.table_names():
            table = db.open_table('embeddings')
            vector_count = table.count_rows()
            print(f'  - 向量数量: {vector_count}')
        else:
            print('  ⚠ LanceDB 表不存在')
    except Exception as e:
        print(f'  ⚠ 无法读取 LanceDB: {e}')

    conn.close()
except Exception as e:
    print(f'  ⚠ 读取数据库失败: {e}')
"
echo ""

# 显示下一步操作
echo -e "${BLUE}下一步操作:${NC}"
echo "  1. 测试检索:"
echo "     python -m poc.search.query --config poc/config/poc.yaml --text '铁塔生锈' --top-k 5"
echo ""
echo "  2. 启动 Web 应用:"
echo "     bash start_all.sh"
echo ""
echo "  3. 查看帮助:"
echo "     bash 重新入库.sh --help"
echo ""
