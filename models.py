"""数据库模型与初始化"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'analyzer.db')


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT NOT NULL DEFAULT 'legacy',
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            date_start TEXT DEFAULT '',
            date_end TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(visitor_id, name)
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            account_id TEXT NOT NULL,
            account_name TEXT DEFAULT '',
            campaign_purpose TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            UNIQUE(project_id, account_id)
        );

        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            batch_id TEXT DEFAULT '',
            material_name TEXT DEFAULT '',
            material_id TEXT DEFAULT '',
            material_type TEXT DEFAULT '',
            campaign_name TEXT DEFAULT '',
            adgroup_name TEXT DEFAULT '',
            cost REAL DEFAULT 0,
            show REAL DEFAULT 0,
            click REAL DEFAULT 0,
            ctr REAL DEFAULT 0,
            conversion REAL DEFAULT 0,
            conversion_cost REAL DEFAULT 0,
            conversion_rate REAL DEFAULT 0,
            roi REAL DEFAULT 0,
            deep_conversion REAL DEFAULT 0,
            deep_conversion_cost REAL DEFAULT 0,
            deep_conversion_rate REAL DEFAULT 0,
            avg_click_cost REAL DEFAULT 0,
            cpm REAL DEFAULT 0,
            click_url TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            video_url TEXT DEFAULT '',
            date_range TEXT DEFAULT '',
            grade TEXT DEFAULT '',
            status TEXT DEFAULT '',
            review_status TEXT DEFAULT '',
            material_evaluation TEXT DEFAULT '',
            linked_adgroup_count INTEGER DEFAULT 0,
            tags TEXT DEFAULT '',
            is_active INTEGER DEFAULT 0,
            is_quality INTEGER DEFAULT 0,
            is_potential INTEGER DEFAULT 0,
            is_quality_grade INTEGER DEFAULT 0,
            is_poor_grade INTEGER DEFAULT 0,
            extra_data TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS material_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            video_code TEXT DEFAULT '',
            price_point TEXT DEFAULT '',
            product TEXT DEFAULT '',
            actor TEXT DEFAULT '',
            bd TEXT DEFAULT '',
            copywriting TEXT DEFAULT '',
            version TEXT DEFAULT '',
            export_time TEXT DEFAULT '',
            source_type TEXT DEFAULT '',
            FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS grade_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT '默认规则',
            s_cost_pct REAL DEFAULT 10.0,
            s_conv_cost_max REAL DEFAULT 0,
            s_conversion_min REAL DEFAULT 3,
            a_cost_pct REAL DEFAULT 30.0,
            a_conv_cost_max REAL DEFAULT 0,
            a_conversion_min REAL DEFAULT 1,
            b_has_conversion INTEGER DEFAULT 1,
            b_conv_cost_max REAL DEFAULT 0,
            c_max_cost REAL DEFAULT 50.0,
            potential_cost_max REAL DEFAULT 500.0,
            potential_ctr_mult REAL DEFAULT 1.5,
            potential_min_show REAL DEFAULT 1000,
            potential_min_click REAL DEFAULT 20,
            is_default INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS import_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            project_name TEXT DEFAULT '',
            account_id TEXT DEFAULT '',
            date_start TEXT DEFAULT '',
            date_end TEXT DEFAULT '',
            rows_total INTEGER DEFAULT 0,
            rows_imported INTEGER DEFAULT 0,
            rows_skipped INTEGER DEFAULT 0,
            field_mapping TEXT DEFAULT '{}',
            status TEXT DEFAULT 'processing',
            error_msg TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS import_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            batch_name TEXT NOT NULL DEFAULT '',
            filename TEXT NOT NULL,
            account_id TEXT DEFAULT '',
            account_name TEXT DEFAULT '',
            rows_count INTEGER DEFAULT 0,
            total_cost REAL DEFAULT 0,
            total_conversion REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_materials_account ON materials(account_id);
        CREATE INDEX IF NOT EXISTS idx_materials_grade ON materials(grade);
        CREATE INDEX IF NOT EXISTS idx_accounts_project ON accounts(project_id);
        CREATE INDEX IF NOT EXISTS idx_material_tags_material ON material_tags(material_id);
        CREATE INDEX IF NOT EXISTS idx_material_tags_actor ON material_tags(actor);
        CREATE INDEX IF NOT EXISTS idx_material_tags_bd ON material_tags(bd);
        CREATE INDEX IF NOT EXISTS idx_material_tags_product ON material_tags(product);
    """)

    # 插入默认分级规则（以消耗+转化数+转化成本为核心）
    cur = conn.execute("SELECT COUNT(*) FROM grade_rules WHERE is_default=1")
    if cur.fetchone()[0] == 0:
        conn.execute("""
            INSERT INTO grade_rules (name, s_cost_pct, s_conversion_min, a_cost_pct, a_conversion_min, b_has_conversion, b_conv_cost_max, c_max_cost, potential_cost_max, potential_ctr_mult, potential_min_show, potential_min_click, is_default)
            VALUES ('默认规则', 10.0, 3, 30.0, 1, 1, 0, 50.0, 500.0, 1.5, 1000, 20, 1)
        """)

    # 迁移：为已有表添加新列（逐列执行，避免某一列已存在导致后续迁移被跳过）
    migrations = [
        "ALTER TABLE materials ADD COLUMN deep_conversion_rate REAL DEFAULT 0",
        "ALTER TABLE materials ADD COLUMN avg_click_cost REAL DEFAULT 0",
        "ALTER TABLE materials ADD COLUMN cpm REAL DEFAULT 0",
        "ALTER TABLE materials ADD COLUMN status TEXT DEFAULT ''",
        "ALTER TABLE materials ADD COLUMN review_status TEXT DEFAULT ''",
        "ALTER TABLE materials ADD COLUMN material_evaluation TEXT DEFAULT ''",
        "ALTER TABLE materials ADD COLUMN linked_adgroup_count INTEGER DEFAULT 0",
        "ALTER TABLE materials ADD COLUMN tags TEXT DEFAULT ''",
        "ALTER TABLE materials ADD COLUMN is_active INTEGER DEFAULT 0",
        "ALTER TABLE materials ADD COLUMN is_quality INTEGER DEFAULT 0",
        "ALTER TABLE materials ADD COLUMN is_potential INTEGER DEFAULT 0",
        "ALTER TABLE materials ADD COLUMN is_quality_grade INTEGER DEFAULT 0",
        "ALTER TABLE materials ADD COLUMN is_poor_grade INTEGER DEFAULT 0",
        "ALTER TABLE projects ADD COLUMN date_start TEXT DEFAULT ''",
        "ALTER TABLE projects ADD COLUMN date_end TEXT DEFAULT ''",
        "ALTER TABLE projects ADD COLUMN visitor_id TEXT NOT NULL DEFAULT 'legacy'",
        "ALTER TABLE import_logs ADD COLUMN account_id TEXT DEFAULT ''",
        "ALTER TABLE import_logs ADD COLUMN date_start TEXT DEFAULT ''",
        "ALTER TABLE import_logs ADD COLUMN date_end TEXT DEFAULT ''",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except Exception:
            pass  # 列已存在则忽略

    # 兼容旧表结构：老版本 projects.name 是全局唯一，会导致不同访客不能创建同名项目。
    # 检测到旧结构时重建 projects 表，改为 visitor_id + name 组合唯一。
    try:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='projects'").fetchone()
        create_sql = row[0] if row else ''
        if 'name TEXT NOT NULL UNIQUE' in create_sql:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("""
                CREATE TABLE projects_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visitor_id TEXT NOT NULL DEFAULT 'legacy',
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    date_start TEXT DEFAULT '',
                    date_end TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(visitor_id, name)
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO projects_new
                    (id, visitor_id, name, description, date_start, date_end, created_at)
                SELECT id, COALESCE(visitor_id, 'legacy'), name,
                       COALESCE(description, ''), COALESCE(date_start, ''), COALESCE(date_end, ''), created_at
                FROM projects
            """)
            conn.execute("DROP TABLE projects")
            conn.execute("ALTER TABLE projects_new RENAME TO projects")
            conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_visitor ON projects(visitor_id)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_visitor_name ON projects(visitor_id, name)")
    except Exception:
        pass

    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_db()
    print("数据库初始化完成")
