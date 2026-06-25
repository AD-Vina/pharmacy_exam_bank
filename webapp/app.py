# -*- coding: utf-8 -*-
import os, json, random, hashlib, re, secrets, time
from collections import defaultdict, deque
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, abort, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..'))

def _resolve_data_path():
    candidates = [
        os.environ.get('QUESTION_DATA_PATH'),
        os.path.join(BASE_DIR, 'data', 'questions_public.json'),
        os.path.join(BASE_DIR, 'data', 'sample_questions.json'),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return os.path.abspath(path)
    return os.path.abspath(candidates[-1])

DATA_PATH = _resolve_data_path()
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(32).hex()
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(INSTANCE_DIR, 'exam.db'))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
app.jinja_env.globals.update(enumerate=enumerate)

SECURITY_ENABLED = os.environ.get('SECURITY_ENABLED', '1') != '0'
SHARE_ACCESS_CODE = os.environ.get('SHARE_ACCESS_CODE', '').strip()
LOCAL_AUTO_LOGIN = os.environ.get('LOCAL_AUTO_LOGIN', '1') != '0'
LOCAL_USERNAME = os.environ.get('LOCAL_USERNAME', 'local')
RATE_LIMITS = defaultdict(deque)
BOT_UA_PATTERNS = re.compile(
    r'(bot|spider|crawler|scrapy|curl|wget|python-requests|httpclient|ahrefs|semrush|mj12|dotbot|bytespider|petalbot)',
    re.I,
)

BOOK_TITLE = '《全国高级卫生专业技术资格考试指导——临床药学》2023版'
CHAPTER_LABELS = {
    'PHARMACOLOGY': '第二章 药理学',
    'PHARMACEUTICS': '第三章 药物制剂及临床应用',
    'DRUG_ANALYSIS': '第四章 药物分析',
    'MEDCHEM': '第五章 药物结构与作用',
    'PHARMACOKINETICS': '第六章 生物药剂学与药物动力学',
    'PHARMACOTHERAPY': '第七章 药物治疗学',
    'PHARMACY_ADMIN': '第八章 药事管理与法规',
    'PHARMACY_SERVICE': '第九章 医院药学服务',
    'CLINICAL_RESEARCH': '第十章 药物临床研究',
}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录'

# ==================== Models ====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='user')  # admin / user
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ExamRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    mode = db.Column(db.String(20), nullable=False)  # exam / practice
    score = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    details = db.Column(db.Text, default='[]')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Bookmark(db.Model):
    """收藏与错题记录"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    qid = db.Column(db.String(32), nullable=False)
    kind = db.Column(db.String(16), default='favorite')  # favorite / mistake / note
    note = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'qid', 'kind', name='uix_user_qid_kind'),)

# ==================== Load Questions ====================
QUESTIONS = []
_QUESTIONS_BY_ID = {}
_QUESTIONS_INDEXED = False
_QUESTIONS_MTIME = None
TYPE_LABELS = {
    'A1': 'A1 单选题',
    'A2': 'A2 病例单选题',
    'A3/A4': 'A3/A4 病例组题',
    'X': 'X 多选题',
    'B1': 'B1 配伍题',
    'CASE': 'CASE 案例分析'
}
DOMAIN_LABELS = {
    'ADMIN_ANTIBIOTIC': '抗菌药管理',
    'ADMIN_HOSPITAL': '医院药事管理',
    'ADMIN_LAW': '药事法规',
    'ADMIN_MONITOR': '重点监控',
    'ADMIN_PREP': '医疗机构制剂',
    'ADMIN_SPECIAL': '特殊药品管理',
    'CR_CLINICAL': '临床试验',
    'CR_HOSPITAL': '医院药学研究',
    'DA_ASSAY': '含量测定',
    'DA_IMPURITIES': '杂质检查',
    'DA_MODERN': '现代仪器分析',
    'DA_PREP_ANALYSIS': '制剂分析',
    'DA_STANDARDS': '质量标准',
    'DRUG_ANALYSIS': '药物分析',
    'MC_NATURAL': '天然药物结构',
    'MC_SYNTHETIC': '合成药物结构',
    'MEDCHEM': '药物化学',
    'PHARMACEUTICS': '药剂学',
    'PHARMACOKINETICS': '药动学',
    'PHARMACOTHERAPY': '药物治疗学',
    'PHARMACY_ADMIN': '药事管理',
    'PHARMACY_SERVICE': '药学服务',
    'PHARMA_INJECT': '注射剂',
    'PHARMA_NOVEL': '新型制剂',
    'PHARMA_ORAL_LIQUID': '口服液体制剂',
    'PHARMA_ORAL_SOLID': '口服固体制剂',
    'PHARMA_TCM': '中药制剂',
    'PHARMA_TOPICAL': '外用制剂',
    'PHARM_ANTIINF': '抗感染药',
    'PHARM_CNS': '中枢神经系统药',
    'PHARM_CV': '心血管系统药',
    'PHARM_ENDO': '内分泌系统药',
    'PHARM_GENERAL': '药理学总论',
    'PHARM_GI': '消化系统药',
    'PHARM_HEME': '血液系统药',
    'PHARM_IMMUNE': '免疫系统药',
    'PHARM_ONCO': '抗肿瘤药',
    'PHARM_PNS': '外周神经系统药',
    'PHARM_RESP': '呼吸系统药',
    'PK_BIO': '生物药剂学',
    'PK_CLINICAL': '临床药动学',
    'PK_DEVELOPMENT': '药动学研究',
    'PK_MODELS': '药动学模型',
    'PK_PROCESS': '药物体内过程',
    'SVC_CLINICAL': '临床药学',
    'SVC_DISPENSING': '调剂学',
    'SVC_INFO': '药学信息',
    'SVC_IV': '静脉用药',
    'SVC_MTM': '药物治疗管理',
    'SVC_SAFETY': '用药安全',
    'SVC_SUPPLY': '药品供应',
    'THER_CV': '心血管治疗',
    'THER_ENDO': '内分泌治疗',
    'THER_GI': '消化系统治疗',
    'THER_HEME': '血液系统治疗',
    'THER_IMMUNE': '免疫治疗',
    'THER_INFECT': '感染性疾病治疗',
    'THER_METAB': '代谢性疾病治疗',
    'THER_NEURO': '神经系统治疗',
    'THER_NUTRITION': '营养支持',
    'THER_ONCO': '肿瘤治疗',
    'THER_PSYCH': '精神心理疾病治疗',
    'THER_RENAL': '肾脏疾病治疗',
    'THER_RESP': '呼吸系统治疗',
    'THER_RHEUM': '风湿免疫治疗',
    'THER_TOXIC': '中毒急救',
    'THER_TRANSPLANT': '器官移植',
    'GUIDE_ANTIMICROBIAL_2015': '抗菌药物临床应用指导',
    'GUIDE_ANTIPLATELET_PGX_2020': '抗血小板药物基因检测',
    'GUIDE_ASCVLDL_MTM_2023': 'ASCVD降胆固醇药物管理',
    'GUIDE_ASTHMA_PRIMARY_2020': '哮喘基层合理用药',
    'GUIDE_BETA_LACTAM_SKIN_2021': 'β内酰胺皮试指导',
    'GUIDE_CANCER_PAIN_PHARM_2019': '癌痛药学管理',
    'GUIDE_CAP_PRIMARY_2020': '成人社区获得性肺炎基层用药',
    'GUIDE_CKD_POTASSIUM_2020': 'CKD血钾管理',
    'GUIDE_COPD_PRIMARY_2020': '慢阻肺基层合理用药',
    'GUIDE_ELDERLY_POLYPHARMACY_2018': '老年多重用药安全',
    'GUIDE_ELDERLY_T2DM_2022': '老年2型糖尿病管理',
    'GUIDE_GOUT_PRIMARY_DRUG_2021': '痛风基层合理用药',
    'GUIDE_HAPVAP_2018': 'HAP/VAP治疗',
    'GUIDE_HF_2016': '心力衰竭合理用药',
    'GUIDE_HP_2022': '幽门螺杆菌治疗',
    'GUIDE_HTN_2022': '高血压合理用药',
    'GUIDE_MTM_2019': '药物治疗管理共识',
    'GUIDE_NEUTROPENIC_FEVER_2020': '中性粒细胞缺乏伴发热',
    'GUIDE_NUTRITION_PHARMACY_2022': '营养药学服务',
    'GUIDE_OFFLABEL_2021': '超说明书用药管理',
    'GUIDE_OSTEOPOROSIS_PRIMARY_DRUG_2021': '骨质疏松基层合理用药',
    'GUIDE_PATHOGEN_THERAPY_TRAINING': '感染病原治疗培训',
    'GUIDE_PA_LRTI_2014': '铜绿假单胞菌下呼吸道感染',
    'GUIDE_PCT_ABX_2020': 'PCT指导抗菌药物',
    'GUIDE_PNP_2020': '周围神经病理性疼痛',
    'GUIDE_PPI_REVIEW_2022': '质子泵抑制剂审方',
    'GUIDE_RX_REVIEW_2018': '医疗机构处方审核规范',
    'GUIDE_T2DM_CKD_POLYPHARMACY_2022': '糖尿病合并CKD多重用药',
    'GUIDE_URTI_PRIMARY_2020': '急性上呼吸道感染合理用药',
    'GUIDE_VANCOMYCIN_TDM_2020': '万古霉素TDM',
    'GUIDE_HYPERTHYROID_PRIMARY_DRUG_2021': '甲亢基层合理用药',
    'GUIDE_HYPOTHYROID_PRIMARY_DRUG_2021': '甲减基层合理用药',
    'BASIC_RESEARCH': '基础研究',
    'BIOPHARMACEUTICS': '生物药剂学',
    'CR_ETHICS': '临床研究伦理',
    'CR_RESEARCH': '临床研究设计',
    'DOSING_DESIGN': '给药方案设计',
    'DOSING_INTERVAL': '给药间隔',
    'EVIDENCE_PHARMACY': '循证药学',
    'MTM': '药物治疗管理',
    'PHARMACOECONOMICS': '药物经济学',
    'PHARMACOGENOMICS': '药物基因组学',
    'PHARMACOLOGY': '药理学',
    'PK_NONLINEAR': '非线性药动学',
    'PK_PARAMETERS': '药动学参数',
    'PK_PD': 'PK/PD',
    'PK_STEADY_STATE': '稳态血药浓度',
    'TDM': '治疗药物监测',
    'TDM_ANALYTE': 'TDM检测物',
    'TDM_INTERPRETATION': 'TDM结果解读',
    'TDM_SAMPLING': 'TDM采样',
    'THER_HEMATOLOGY': '血液系统治疗',
}

SOURCE_TYPE_LABELS = {
    'textbook': '书本',
    'guideline': '指南',
    'other': '其他',
}

# Canonical display labels. This overlay keeps internal domain codes out of the UI.
DOMAIN_LABELS.update({
    'ADMIN_ANTIBIOTIC': '抗菌药管理',
    'ADMIN_HOSPITAL': '医院药事管理',
    'ADMIN_LAW': '药事法规',
    'ADMIN_MONITOR': '重点监控',
    'ADMIN_PREP': '医疗机构制剂',
    'ADMIN_SPECIAL': '特殊药品管理',
    'BASIC_RESEARCH': '基础研究',
    'BIOPHARMACEUTICS': '生物药剂学',
    'CR_CLINICAL': '临床试验',
    'CR_ETHICS': '临床研究伦理',
    'CR_HOSPITAL': '医院药学研究',
    'CR_RESEARCH': '临床研究设计',
    'DA_ASSAY': '含量测定',
    'DA_IMPURITIES': '杂质检查',
    'DA_MODERN': '现代仪器分析',
    'DA_PREP_ANALYSIS': '制剂分析',
    'DA_STANDARDS': '质量标准',
    'DRUG_ANALYSIS': '药物分析',
    'DOSING_DESIGN': '给药方案设计',
    'DOSING_INTERVAL': '给药间隔',
    'EVIDENCE_PHARMACY': '循证药学',
    'GUIDE_ANTIMICROBIAL_2015': '抗菌药物临床应用指导原则（2015版）',
    'GUIDE_ANTIPLATELET_PGX_2020': '抗血小板药物药物基因组学',
    'GUIDE_ASCVLDL_MTM_2023': 'ASCVD降胆固醇药物治疗管理',
    'GUIDE_ASTHMA_PRIMARY_2020': '支气管哮喘基层合理用药',
    'GUIDE_BETA_LACTAM_SKIN_2021': 'β内酰胺类抗菌药物皮试',
    'GUIDE_CANCER_PAIN_PHARM_2019': '癌痛药学管理',
    'GUIDE_CAP_PRIMARY_2020': '成人社区获得性肺炎基层用药',
    'GUIDE_CKD_POTASSIUM_2020': '慢性肾脏病血钾管理',
    'GUIDE_COPD_PRIMARY_2020': '慢阻肺基层合理用药',
    'GUIDE_ELDERLY_POLYPHARMACY_2018': '老年人多重用药安全',
    'GUIDE_ELDERLY_T2DM_2022': '老年2型糖尿病管理',
    'GUIDE_GOUT_PRIMARY_DRUG_2021': '痛风基层合理用药',
    'GUIDE_HAPVAP_2018': 'HAP/VAP抗感染治疗',
    'GUIDE_HF_2016': '心力衰竭合理用药',
    'GUIDE_HP_2022': '幽门螺杆菌感染治疗',
    'GUIDE_HTN_2022': '高血压合理用药',
    'GUIDE_HYPERTHYROID_PRIMARY_DRUG_2021': '甲亢基层合理用药',
    'GUIDE_HYPOTHYROID_PRIMARY_DRUG_2021': '甲减基层合理用药',
    'GUIDE_MTM_2019': '药物治疗管理共识',
    'GUIDE_NEUTROPENIC_FEVER_2020': '中性粒细胞缺乏伴发热',
    'GUIDE_NUTRITION_PHARMACY_2022': '营养药学服务',
    'GUIDE_OFFLABEL_2021': '超说明书用药管理',
    'GUIDE_OSTEOPOROSIS_PRIMARY_DRUG_2021': '骨质疏松基层合理用药',
    'GUIDE_PATHOGEN_THERAPY_TRAINING': '感染病原治疗培训',
    'GUIDE_PA_LRTI_2014': '铜绿假单胞菌下呼吸道感染',
    'GUIDE_PCT_ABX_2020': 'PCT指导抗菌药物使用',
    'GUIDE_PNP_2020': '周围神经病理性疼痛',
    'GUIDE_PPI_REVIEW_2022': '质子泵抑制剂处方审核',
    'GUIDE_RX_REVIEW_2018': '医疗机构处方审核规范',
    'GUIDE_T2DM_CKD_POLYPHARMACY_2022': '糖尿病合并CKD多重用药',
    'GUIDE_URTI_PRIMARY_2020': '急性上呼吸道感染基层用药',
    'GUIDE_VANCOMYCIN_TDM_2020': '万古霉素TDM',
    'MC_NATURAL': '天然药物结构',
    'MC_SYNTHETIC': '合成药物结构',
    'MEDCHEM': '药物化学',
    'MTM': '药物治疗管理',
    'PHARMACEUTICS': '药剂学',
    'PHARMACOECONOMICS': '药物经济学',
    'PHARMACOGENOMICS': '药物基因组学',
    'PHARMACOKINETICS': '药动学',
    'PHARMACOLOGY': '药理学',
    'PHARMACOTHERAPY': '药物治疗学',
    'PHARMACY_ADMIN': '药事管理',
    'PHARMACY_SERVICE': '药学服务',
    'PHARMA_INJECT': '注射剂',
    'PHARMA_NOVEL': '新型制剂',
    'PHARMA_ORAL_LIQUID': '口服液体制剂',
    'PHARMA_ORAL_SOLID': '口服固体制剂',
    'PHARMA_TCM': '中药制剂',
    'PHARMA_TOPICAL': '外用制剂',
    'PHARM_ANTIINF': '抗感染药',
    'PHARM_CNS': '中枢神经系统药',
    'PHARM_CV': '心血管系统药',
    'PHARM_ENDO': '内分泌系统药',
    'PHARM_GENERAL': '药理学总论',
    'PHARM_GI': '消化系统药',
    'PHARM_HEME': '血液系统药',
    'PHARM_IMMUNE': '免疫系统药',
    'PHARM_ONCO': '抗肿瘤药',
    'PHARM_PNS': '外周神经系统药',
    'PHARM_RESP': '呼吸系统药',
    'PK_BIO': '生物药剂学',
    'PK_CLINICAL': '临床药动学',
    'PK_DEVELOPMENT': '药动学研究',
    'PK_MODELS': '药动学模型',
    'PK_NONLINEAR': '非线性药动学',
    'PK_PARAMETERS': '药动学参数',
    'PK_PD': 'PK/PD',
    'PK_PROCESS': '药物体内过程',
    'PK_STEADY_STATE': '稳态血药浓度',
    'SVC_CLINICAL': '临床药学',
    'SVC_DISPENSING': '调剂学',
    'SVC_INFO': '药学信息',
    'SVC_IV': '静脉用药',
    'SVC_MTM': '药物治疗管理',
    'SVC_SAFETY': '用药安全',
    'SVC_SUPPLY': '药品供应',
    'TDM': '治疗药物监测',
    'TDM_ANALYTE': 'TDM检测物',
    'TDM_INTERPRETATION': 'TDM结果解读',
    'TDM_SAMPLING': 'TDM采样',
    'THER_CV': '心血管治疗',
    'THER_ENDO': '内分泌治疗',
    'THER_GI': '消化系统治疗',
    'THER_HEMATOLOGY': '血液系统治疗',
    'THER_HEME': '血液系统治疗',
    'THER_IMMUNE': '免疫治疗',
    'THER_INFECT': '感染性疾病治疗',
    'THER_METAB': '代谢性疾病治疗',
    'THER_NEURO': '神经系统治疗',
    'THER_NUTRITION': '营养支持',
    'THER_ONCO': '肿瘤治疗',
    'THER_PSYCH': '精神心理疾病治疗',
    'THER_RENAL': '肾脏疾病治疗',
    'THER_RESP': '呼吸系统治疗',
    'THER_RHEUM': '风湿免疫治疗',
    'THER_TOXIC': '中毒急救',
    'THER_TRANSPLANT': '器官移植',
})

def question_source_type(question):
    value = (question or {}).get('source_type') or ''
    if value in SOURCE_TYPE_LABELS:
        return value
    domain = (question or {}).get('domain') or ''
    if domain.startswith('GUIDE_'):
        return 'guideline'
    return 'textbook'

def domain_label(domain):
    return DOMAIN_LABELS.get(domain, domain)

def build_domain_groups(questions):
    grouped = {}
    for q in questions:
        domain = q.get('domain')
        if not domain:
            continue
        source_type = question_source_type(q)
        grouped.setdefault(source_type, {})
        grouped[source_type][domain] = grouped[source_type].get(domain, 0) + 1

    order = {'textbook': 0, 'guideline': 1, 'other': 2}
    result = []
    for source_type in sorted(grouped, key=lambda k: (order.get(k, 99), SOURCE_TYPE_LABELS.get(k, k))):
        domains = [
            {'name': name, 'label': domain_label(name), 'count': count}
            for name, count in grouped[source_type].items()
        ]
        domains.sort(key=lambda item: (-item['count'], item['label']))
        result.append({
            'key': source_type,
            'label': SOURCE_TYPE_LABELS.get(source_type, source_type),
            'count': sum(item['count'] for item in domains),
            'domains': domains,
        })
    return result

def domain_options_for_source(questions, source_type=''):
    domains = {}
    for q in questions:
        if source_type and question_source_type(q) != source_type:
            continue
        domain = q.get('domain')
        if domain:
            domains[domain] = domain_label(domain)
    return [name for name, _ in sorted(domains.items(), key=lambda item: item[1])]

def load_questions():
    global QUESTIONS, _QUESTIONS_BY_ID, _QUESTIONS_INDEXED, _QUESTIONS_MTIME
    try:
        current_mtime = os.path.getmtime(DATA_PATH)
    except OSError:
        current_mtime = None
    if not _QUESTIONS_INDEXED or current_mtime != _QUESTIONS_MTIME:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            QUESTIONS = json.load(f)
        _QUESTIONS_BY_ID = {q['id']: q for q in QUESTIONS}
        _QUESTIONS_INDEXED = True
        _QUESTIONS_MTIME = current_mtime
    return QUESTIONS

def get_question_by_id(qid):
    load_questions()
    return _QUESTIONS_BY_ID.get(qid)

def init_users():
    if LOCAL_AUTO_LOGIN:
        return
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'Admin@12345')
    demo_pass = os.environ.get('DEMO_PASSWORD', 'Demo@12345')
    reset_passwords = os.environ.get('RESET_DEFAULT_PASSWORDS', '0') == '1'
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        db.session.add(User(username='admin', password_hash=generate_password_hash(admin_pass), role='admin'))
    elif reset_passwords and admin_pass:
        admin.password_hash = generate_password_hash(admin_pass)
    demo = User.query.filter_by(username='demo').first()
    if not demo:
        db.session.add(User(username='demo', password_hash=generate_password_hash(demo_pass), role='user'))
    elif reset_passwords and demo_pass:
        demo.password_hash = generate_password_hash(demo_pass)
    db.session.commit()

def get_or_create_local_user():
    user = User.query.filter_by(username=LOCAL_USERNAME).first()
    if user:
        return user
    user = User(
        username=LOCAL_USERNAME,
        password_hash=generate_password_hash(secrets.token_urlsafe(18)),
        role='local',
    )
    db.session.add(user)
    db.session.commit()
    return user

def client_ip():
    return (
        request.headers.get('CF-Connecting-IP')
        or request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        or request.remote_addr
        or 'unknown'
    )

def check_rate_limit(bucket, limit, window_seconds):
    now = time.time()
    key = f'{bucket}:{client_ip()}'
    hits = RATE_LIMITS[key]
    while hits and hits[0] <= now - window_seconds:
        hits.popleft()
    if len(hits) >= limit:
        return False
    hits.append(now)
    return True

def require_share_gate():
    if not SECURITY_ENABLED or not SHARE_ACCESS_CODE:
        return False
    return not session.get('share_access_ok')

@app.before_request
def security_before_request():
    endpoint = request.endpoint or ''
    if endpoint in {'static', 'healthz', 'robots_txt'}:
        return None

    if LOCAL_AUTO_LOGIN:
        if not current_user.is_authenticated:
            login_user(get_or_create_local_user())
        if endpoint in {'login', 'guest_login', 'share_gate'}:
            return redirect(url_for('index'))

    if SECURITY_ENABLED:
        ua = request.headers.get('User-Agent', '')
        if not ua or BOT_UA_PATTERNS.search(ua):
            abort(403)
        if not check_rate_limit('global', 240, 60):
            abort(429)
        if endpoint in {'login', 'guest_login', 'share_gate'} and not check_rate_limit('auth', 30, 600):
            abort(429)

    if SHARE_ACCESS_CODE and request.args.get('access') == SHARE_ACCESS_CODE:
        session['share_access_ok'] = True
        return redirect(url_for('index'))

    if require_share_gate() and endpoint != 'share_gate':
        return redirect(url_for('share_gate', next=request.full_path if request.query_string else request.path))

    return None

@app.after_request
def security_after_request(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "form-action 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    if request.endpoint != 'static':
        response.headers['Cache-Control'] = 'no-store'
    return response

# ==================== Scoring ====================
def score_answer(question, user_answer):
    """user_answer: 前端传回的原始值（list 或 dict）"""
    qtype = question['type']
    correct = question['answer']['correct']
    if qtype == 'B1':
        # user_answer: list of list indices, e.g. [[0],[2],...]
        if not isinstance(user_answer, list):
            return 0
        score = 0
        for idx, sub in enumerate(correct):
            ua = user_answer[idx] if idx < len(user_answer) else []
            if not isinstance(ua, list):
                ua = [ua]
            # normalize to ints
            ua_ints = [int(x) for x in ua if x is not None and str(x).strip() != '']
            if sorted(ua_ints) == sorted(sub):
                score += 1
        return score
    elif qtype == 'X':
        if not isinstance(user_answer, list):
            return 0
        ua_ints = sorted([int(x) for x in user_answer if x is not None])
        return 1 if ua_ints == sorted(correct) else 0
    else:
        # A1, A2, CASE: single choice
        try:
            ua = int(user_answer[0]) if isinstance(user_answer, list) else int(user_answer)
        except (ValueError, TypeError, IndexError):
            return 0
        return 1 if ua in correct else 0

def extract_answer_from_request(question, request_form):
    """从 request.form 提取用户答案，统一返回可序列化的结构"""
    qtype = question['type']
    qid = question['id']
    if qtype == 'B1':
        answers = []
        items = question['content'].get('items', [])
        for i in range(len(items)):
            vals = request_form.getlist(f'answer_{i}')
            answers.append([int(v) for v in vals if v.strip() != ''])
        return answers
    elif qtype == 'X':
        vals = request_form.getlist('answer')
        return [int(v) for v in vals if v.strip() != '']
    else:
        v = request_form.get('answer', '')
        return [int(v)] if v.strip() != '' else []

def get_letter(idx):
    """选项索引转字母，超出 26 用 A1, B1..."""
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return ''
    if idx < 0:
        return ''
    if idx < 26:
        return chr(65 + idx)
    return chr(65 + (idx % 26)) + str(idx // 26 + 1)

def format_answer_labels(value):
    if value is None or value == '':
        return '未作答'
    if not isinstance(value, list):
        value = [value]
    if value and isinstance(value[0], list):
        return ' / '.join(format_answer_labels(item) for item in value)
    labels = []
    for item in value:
        try:
            labels.append(get_letter(int(item)))
        except (TypeError, ValueError):
            continue
    return ', '.join(labels) if labels else '未作答'

def format_answer_with_text(question, value):
    labels = format_answer_labels(value)
    if labels == '未作答':
        return labels
    content = (question or {}).get('content') or {}
    options = content.get('shared_options') or content.get('options') or []
    if not isinstance(value, list):
        value = [value]
    if value and isinstance(value[0], list):
        return labels
    parts = []
    for item in value:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(options):
            parts.append(f"{get_letter(idx)}. {options[idx]}")
    return '；'.join(parts) if parts else labels

def _normalize_answer_values(value):
    if value is None or value == '':
        return []
    if not isinstance(value, list):
        value = [value]
    values = []
    for item in value:
        if isinstance(item, list):
            continue
        try:
            values.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(values)

def answers_match(user_answer, correct_answer):
    return _normalize_answer_values(user_answer) == _normalize_answer_values(correct_answer)

def get_option_explanations(question):
    explanation = (question or {}).get('explanation') or {}
    items = explanation.get('option_analysis') or explanation.get('wrong_reasons') or []
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = _clean_source_text(item.get('text'))
        if not text or '???' in text:
            continue
        try:
            option = int(item.get('option'))
        except (TypeError, ValueError):
            continue
        if option < 0:
            continue
        cleaned.append({'option': option, 'text': text})
    cleaned.sort(key=lambda item: item['option'])
    return cleaned

_DOMAIN_META_BY_ID = None
_KNOWLEDGE_SOURCE_BY_ID = None
_SOURCE_TEXT_INDEX = None

EXCERPT_KEYS = (
    'source_excerpt', 'source_quote', 'source_paragraph', 'original_text',
    'evidence_text', 'excerpt', 'quote', 'paragraph'
)
SOURCE_SNIPPET_MAX_CHARS = 180

def _as_list(value):
    if value is None or value == '':
        return []
    if isinstance(value, list):
        return value
    return [value]

def _clean_source_text(value):
    if value is None:
        return ''
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return re.sub(r'\s+', ' ', value).strip()
    return ''

def _dedupe(values):
    result, seen = [], set()
    for value in values:
        value = _clean_source_text(value)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result

def _load_domain_meta():
    global _DOMAIN_META_BY_ID
    if _DOMAIN_META_BY_ID is not None:
        return _DOMAIN_META_BY_ID

    meta = {}
    path = os.path.join(PROJECT_ROOT, 'db', 'knowledge_domains.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for domain in data.get('domains', []):
            domain_id = domain.get('id', '')
            meta[domain_id] = {
                'id': domain_id,
                'name': domain.get('name', ''),
                'parent_id': domain_id,
                'parent_name': domain.get('name', ''),
                'sub_id': '',
                'sub_name': '',
            }
            for sub in domain.get('subdomains', []):
                sub_id = sub.get('id', '')
                meta[sub_id] = {
                    'id': sub_id,
                    'name': sub.get('name', ''),
                    'parent_id': domain_id,
                    'parent_name': domain.get('name', ''),
                    'sub_id': sub_id,
                    'sub_name': sub.get('name', ''),
                }
    except (OSError, json.JSONDecodeError):
        meta = {}

    _DOMAIN_META_BY_ID = meta
    return meta

def _parse_frontmatter(path):
    meta = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            first = f.readline().strip()
            if first != '---':
                return meta
            for line in f:
                line = line.rstrip('\n')
                if line.strip() == '---':
                    break
                if ':' not in line:
                    continue
                key, value = line.split(':', 1)
                meta[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return {}
    return meta

def _load_knowledge_sources():
    global _KNOWLEDGE_SOURCE_BY_ID
    if _KNOWLEDGE_SOURCE_BY_ID is not None:
        return _KNOWLEDGE_SOURCE_BY_ID

    result = {}
    root = os.path.join(PROJECT_ROOT, 'knowledge_points')
    if os.path.isdir(root):
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                if not filename.endswith('.md'):
                    continue
                path = os.path.join(dirpath, filename)
                meta = _parse_frontmatter(path)
                if not meta:
                    continue
                stem = os.path.splitext(filename)[0]
                if meta.get('id'):
                    result[meta['id']] = meta
                result[stem] = meta

    _KNOWLEDGE_SOURCE_BY_ID = result
    return result

def _format_pages(pages):
    pages = _dedupe([str(p) for p in _as_list(pages)])
    return '、'.join(pages)

def _normalize_book_title(title):
    title = _clean_source_text(title)
    if not title:
        return ''
    if title.startswith('临床药学考试指导'):
        return title.replace('临床药学考试指导', BOOK_TITLE, 1)
    if title == '临床药学考试指导':
        return BOOK_TITLE
    return title

def _format_domain_reference(ref, question=None, pages=None):
    ref = _clean_source_text(ref)
    if not ref and question:
        ref = question.get('domain', '')
    domain_id, topic = ref, ''
    if '/' in ref:
        domain_id, topic = ref.split('/', 1)
        domain_id, topic = domain_id.strip(), topic.strip()

    meta = _load_domain_meta().get(domain_id)
    if not meta:
        return ''

    chapter = CHAPTER_LABELS.get(meta.get('parent_id'), meta.get('parent_name', ''))
    details = []
    if meta.get('sub_name') and topic:
        details.append(f"{meta['sub_name']}：{topic}")
    elif topic:
        details.append(topic)
    elif question and question.get('subdomain'):
        details.append(question.get('subdomain'))
    elif meta.get('sub_name'):
        details.append(meta.get('sub_name'))

    page_text = _format_pages(pages)
    if page_text:
        details.append(page_text)
    detail_text = f"（{'；'.join(_dedupe(details))}）" if details else ''
    return f"{BOOK_TITLE} {chapter}{detail_text}".strip()

def _format_knowledge_source(meta, pages=None):
    source = _normalize_book_title(meta.get('source')) or BOOK_TITLE
    domain_meta = _load_domain_meta().get(meta.get('domain', '')) or {}
    chapter = CHAPTER_LABELS.get(domain_meta.get('parent_id'), '')
    details = []
    if meta.get('subdomain'):
        details.append(meta.get('subdomain'))
    elif domain_meta.get('sub_name'):
        details.append(domain_meta.get('sub_name'))

    source_pages = _as_list(meta.get('source_page')) + _as_list(pages)
    page_text = _format_pages(source_pages)
    if page_text:
        details.append(page_text)

    detail_text = f"（{'；'.join(_dedupe(details))}）" if details else ''
    return f"{source} {chapter}{detail_text}".strip()

def _looks_internal_source(token):
    token = _clean_source_text(token)
    lower = token.lower()
    if not token:
        return True
    if any(mark in lower for mark in ('db/', '.json', '.md', 'source_file')):
        return True
    if re.fullmatch(r'[A-Z0-9]+(?:_[A-Z0-9]+){1,}', token):
        return True
    if re.fullmatch(r'[a-z0-9]+(?:_[a-z0-9]+){1,}', token):
        return True
    return False

def _format_source_token(token, question=None, pages=None):
    token = _clean_source_text(token)
    if not token:
        return ''

    if token.startswith('db/knowledge_domains.json:'):
        ref = token.split(':', 1)[1].strip()
        return _format_domain_reference(ref, question, pages)

    knowledge_meta = _load_knowledge_sources().get(token)
    if knowledge_meta:
        return _format_knowledge_source(knowledge_meta, pages)

    if token in _load_domain_meta():
        return _format_domain_reference(token, question, pages)

    title = _normalize_book_title(token)
    if title and not _looks_internal_source(title):
        page_text = _format_pages(pages)
        if page_text and page_text not in title:
            return f"{title}（{page_text}）"
        return title

    return ''

def _collect_source_parts(question):
    question = question or {}
    explanation = question.get('explanation') or {}
    raw_sources = []
    if explanation.get('source'):
        raw_sources.append(explanation.get('source'))
    elif question.get('source'):
        raw_sources.append(question.get('source'))
    elif question.get('source_ref'):
        raw_sources.append(question.get('source_ref'))

    tokens, pages = [], []
    for raw in raw_sources:
        if isinstance(raw, dict):
            title = raw.get('title') or raw.get('name') or raw.get('source')
            if title:
                tokens.extend([p.strip() for p in re.split(r'\s*;\s*', str(title)) if p.strip()])
            for key in ('pages', 'page', 'source_page'):
                pages.extend(_as_list(raw.get(key)))
        elif isinstance(raw, list):
            for item in raw:
                child_tokens, child_pages = _collect_source_parts({'explanation': {'source': item}})
                tokens.extend(child_tokens)
                pages.extend(child_pages)
        elif isinstance(raw, str):
            tokens.extend([p.strip() for p in re.split(r'\s*;\s*', raw) if p.strip()])

    return tokens, pages

def _find_source_file(base_path, file_name):
    if not base_path or not file_name or not os.path.isdir(base_path):
        return ''
    direct = os.path.join(base_path, '根目录', file_name)
    if os.path.exists(direct):
        return direct
    for dirpath, _, filenames in os.walk(base_path):
        if file_name in filenames:
            return os.path.join(dirpath, file_name)
    return ''

def _load_source_text_index():
    global _SOURCE_TEXT_INDEX
    if _SOURCE_TEXT_INDEX is not None:
        return _SOURCE_TEXT_INDEX

    entries = []
    index_path = os.path.join(PROJECT_ROOT, 'materials_index', 'guideline_index.json')
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)
    except (OSError, json.JSONDecodeError):
        _SOURCE_TEXT_INDEX = []
        return _SOURCE_TEXT_INDEX

    base_path = index_data.get('base_path', '')
    source_files = []
    core_file = (index_data.get('core_textbook') or {}).get('file', '')
    core_path = _find_source_file(base_path, core_file)
    if core_path:
        source_files.append(core_path)
    for name in index_data.get('priority_guidelines', []):
        path = _find_source_file(base_path, name)
        if path:
            source_files.append(path)

    for path in _dedupe(source_files):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for lineno, line in enumerate(f, 1):
                    text = _clean_source_text(line)
                    is_chapter_heading = bool(re.search(r'第[一二三四五六七八九十]+章', text))
                    if len(text) < 14 and not is_chapter_heading:
                        continue
                    if text.startswith('|') or re.fullmatch(r'[\d\s.、-]+', text):
                        continue
                    entries.append({
                        'path': path,
                        'file': os.path.basename(path),
                        'line': lineno,
                        'text': text,
                        'norm': re.sub(r'\s+', '', text).lower(),
                    })
        except OSError:
            continue

    _SOURCE_TEXT_INDEX = entries
    return entries

def _core_textbook_entries():
    entries = _load_source_text_index()
    return [entry for entry in entries if '全国高级卫生专业技术资格考试指导' in entry.get('file', '')]

def _parent_domain_id(question):
    domain = (question or {}).get('domain', '')
    meta = _load_domain_meta().get(domain)
    if meta and meta.get('parent_id'):
        return meta['parent_id']
    if domain in CHAPTER_LABELS:
        return domain
    return ''

def _chapter_heading_for_question(question):
    parent_id = _parent_domain_id(question)
    return CHAPTER_LABELS.get(parent_id, '')

def _chapter_fallback_excerpt(question):
    heading = _chapter_heading_for_question(question)
    if not heading:
        return ''
    normalized_heading = re.sub(r'\s+', '', heading).lower()
    candidates = []
    for entry in _core_textbook_entries():
        if normalized_heading and normalized_heading in entry.get('norm', ''):
            candidates.append(entry)
    if not candidates:
        return ''

    start = next((entry for entry in candidates if entry.get('line', 0) > 1000), candidates[0])
    entries = _core_textbook_entries()
    by_line = {entry['line']: entry for entry in entries if entry.get('path') == start.get('path')}
    for offset in range(1, 80):
        entry = by_line.get(start['line'] + offset)
        if not entry:
            continue
        text = entry.get('text', '')
        if len(text) < 24:
            continue
        if '第' in text[:5] and '章' in text[:8]:
            continue
        snippet = text[:SOURCE_SNIPPET_MAX_CHARS].rstrip()
        if len(text) > SOURCE_SNIPPET_MAX_CHARS:
            snippet += '...'
        return f"{start['file']} 第{entry['line']}行：{snippet}"
    return ''

def _extract_search_terms(text):
    text = _clean_source_text(text)
    if not text:
        return []
    terms = []
    terms.extend(re.findall(r'[A-Za-z][A-Za-z0-9+./-]{1,}', text))
    terms.extend(re.findall(r'[\u4e00-\u9fff]{2,8}', text))
    return terms

def _correct_option_texts(question):
    content = (question or {}).get('content') or {}
    answer = (question or {}).get('answer') or {}
    correct = answer.get('correct') or []
    options = content.get('shared_options') or content.get('options') or []
    result = []
    if correct and isinstance(correct[0], list):
        for group in correct:
            for idx in group:
                if isinstance(idx, int) and 0 <= idx < len(options):
                    result.append(options[idx])
    else:
        for idx in correct:
            if isinstance(idx, int) and 0 <= idx < len(options):
                result.append(options[idx])
    return _dedupe(result)

def _source_search_terms(question):
    question = question or {}
    explanation = question.get('explanation') or {}
    content = question.get('content') or {}
    texts = []
    texts.extend(_correct_option_texts(question))
    texts.extend([
        explanation.get('key_point', ''),
        explanation.get('correct_reason', ''),
        content.get('stem', ''),
        content.get('scenario', ''),
        question.get('subdomain', ''),
        question.get('domain', ''),
    ])

    terms = []
    for text in texts:
        terms.extend(_extract_search_terms(text))

    stop_terms = {
        '正确', '错误', '患者', '药物', '治疗', '用药', '临床', '应当', '可以',
        '不是', '属于', '主要', '最应', '最可能', '最合理', '处理', '原则',
        '教材', '章节', '药学', '考试', '指导'
    }
    clean_terms = []
    for term in terms:
        term = term.strip()
        if len(term) < 2 or term in stop_terms:
            continue
        clean_terms.append(term)
    return _dedupe(clean_terms)[:36]

def _find_source_excerpt(question):
    terms = _source_search_terms(question)
    if not terms:
        return ''
    index = _load_source_text_index()
    if not index:
        return _chapter_fallback_excerpt(question)

    best = None
    best_score = 0
    norm_terms = [(term, re.sub(r'\s+', '', term).lower()) for term in terms]
    for entry in index:
        text = entry['norm']
        score = 0
        for raw, term in norm_terms:
            if term and term in text:
                score += min(max(len(raw), 2), 12)
        if score > best_score:
            best_score = score
            best = entry

    if not best or best_score < 8:
        return _chapter_fallback_excerpt(question)
    snippet = best['text']
    if len(snippet) > SOURCE_SNIPPET_MAX_CHARS:
        snippet = snippet[:SOURCE_SNIPPET_MAX_CHARS].rstrip() + '...'
    return f"{best['file']} 第{best['line']}行：{snippet}"

def format_source(question):
    tokens, pages = _collect_source_parts(question)
    displays = []
    for token in tokens:
        display = _format_source_token(token, question, pages)
        if display:
            displays.append(display)

    if not displays:
        fallback = _format_domain_reference((question or {}).get('domain', ''), question, pages)
        if fallback:
            displays.append(fallback)

    return '；'.join(_dedupe(displays))

def get_source_excerpt(question):
    question = question or {}
    explanation = question.get('explanation') or {}
    for container in (explanation, explanation.get('source') or {}, question):
        if not isinstance(container, dict):
            continue
        for key in EXCERPT_KEYS:
            value = container.get(key)
            if isinstance(value, list):
                value = ' '.join([_clean_source_text(v) for v in value])
            value = _clean_source_text(value)
            if value:
                return value
    return _find_source_excerpt(question)

app.jinja_env.globals.update(
    get_letter=get_letter,
    domain_labels=DOMAIN_LABELS,
    domain_label=domain_label,
    source_type_labels=SOURCE_TYPE_LABELS,
    question_source_type=question_source_type,
    format_source=format_source,
    get_source_excerpt=get_source_excerpt,
    format_answer_labels=format_answer_labels,
    format_answer_with_text=format_answer_with_text,
    answers_match=answers_match,
    get_option_explanations=get_option_explanations,
)

@app.context_processor
def inject_template_helpers():
    return {
        'get_letter': get_letter,
        'domain_labels': DOMAIN_LABELS,
        'domain_label': domain_label,
        'source_type_labels': SOURCE_TYPE_LABELS,
        'question_source_type': question_source_type,
        'type_labels': TYPE_LABELS,
        'format_source': format_source,
        'get_source_excerpt': get_source_excerpt,
        'format_answer_labels': format_answer_labels,
        'format_answer_with_text': format_answer_with_text,
        'answers_match': answers_match,
        'get_option_explanations': get_option_explanations,
        'local_auto_login': LOCAL_AUTO_LOGIN,
    }

# ==================== Routes ====================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/gate', methods=['GET', 'POST'])
def share_gate():
    if not SHARE_ACCESS_CODE:
        return redirect(url_for('login'))
    next_url = request.values.get('next') or url_for('index')
    if not next_url.startswith('/'):
        next_url = url_for('index')
    if request.method == 'POST':
        code = request.form.get('access_code', '').strip()
        if secrets.compare_digest(code, SHARE_ACCESS_CODE):
            session['share_access_ok'] = True
            return redirect(next_url)
        flash('访问码错误', 'danger')
    return render_template('gate.html', next_url=next_url)

@app.route('/robots.txt')
def robots_txt():
    return Response('User-agent: *\nDisallow: /\n', mimetype='text/plain')

@app.route('/')
@login_required
def index():
    qs = load_questions()
    stats = {}
    for q in qs:
        stats[q['type']] = stats.get(q['type'], 0) + 1
    records = ExamRecord.query.filter_by(user_id=current_user.id).order_by(ExamRecord.created_at.desc()).limit(10).all()
    # 错题统计
    mistake_count = Bookmark.query.filter_by(user_id=current_user.id, kind='mistake').count()
    favorite_count = Bookmark.query.filter_by(user_id=current_user.id, kind='favorite').count()
    # 按领域统计
    domain_groups = build_domain_groups(qs)
    domain_stats = [item for group in domain_groups for item in group['domains']]
    return render_template('dashboard.html', stats=stats, type_labels=TYPE_LABELS, records=records, total=len(qs),
                           mistake_count=mistake_count, favorite_count=favorite_count, domain_stats=domain_stats,
                           domain_groups=domain_groups, domain_labels=DOMAIN_LABELS, source_type_labels=SOURCE_TYPE_LABELS)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if LOCAL_AUTO_LOGIN:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))
        flash('用户名或密码错误', 'danger')
    return render_template('login.html')

@app.route('/guest-login', methods=['POST'])
def guest_login():
    if LOCAL_AUTO_LOGIN:
        return redirect(url_for('index'))
    if os.environ.get('ALLOW_GUEST_LOGIN', '1') == '0':
        flash('游客入口已关闭', 'warning')
        return redirect(url_for('login'))
    for _ in range(8):
        username = 'guest_' + secrets.token_hex(4)
        if not User.query.filter_by(username=username).first():
            user = User(
                username=username,
                password_hash=generate_password_hash(secrets.token_urlsafe(18)),
                role='guest',
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for('index'))
    flash('游客账号创建失败，请稍后重试', 'warning')
    return redirect(url_for('login'))

@app.route('/healthz')
def healthz():
    return jsonify({'ok': True, 'questions': len(load_questions())})

@app.route('/logout')
@login_required
def logout():
    if LOCAL_AUTO_LOGIN:
        return redirect(url_for('index'))
    logout_user()
    return redirect(url_for('login'))

@app.route('/browse')
@login_required
def browse():
    qtype = request.args.get('type', '')
    source_type = request.args.get('source_type', '')
    domain = request.args.get('domain', '')
    keyword = request.args.get('keyword', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    qs = load_questions()
    if qtype:
        qs = [q for q in qs if q['type'] == qtype]
    if source_type:
        qs = [q for q in qs if question_source_type(q) == source_type]
    if domain:
        qs = [q for q in qs if q.get('domain') == domain]
    if keyword:
        low = keyword.lower()
        filtered = []
        for q in qs:
            texts = [q.get('domain', ''), q.get('subdomain', '')]
            c = q.get('content', {})
            if isinstance(c, dict):
                texts.append(c.get('stem', ''))
                texts.append(c.get('scenario', ''))
                texts.append(' '.join(c.get('options', [])))
                texts.append(' '.join(c.get('shared_options', [])))
                for it in c.get('items', []):
                    texts.append(it.get('stem', ''))
            if any(low in t.lower() for t in texts if t):
                filtered.append(q)
        qs = filtered
    total = len(qs)
    start = (page - 1) * per_page
    end = start + per_page
    page_qs = qs[start:end]
    all_questions = load_questions()
    domains = domain_options_for_source(all_questions, source_type)
    domain_groups = build_domain_groups(all_questions)
    total_pages = (total + per_page - 1) // per_page if total else 1
    return render_template('browse.html', questions=page_qs, type_labels=TYPE_LABELS, domains=domains, qtype=qtype,
                           source_type=source_type, domain=domain, keyword=keyword, page=page,
                           total_pages=total_pages, total=total, per_page=per_page, domain_labels=DOMAIN_LABELS,
                           domain_groups=domain_groups, source_type_labels=SOURCE_TYPE_LABELS)

@app.route('/practice')
@login_required
def practice():
    qtype = request.args.get('type', '')
    qs = load_questions()
    if qtype:
        qs = [q for q in qs if q['type'] == qtype]
    if not qs:
        flash('题库为空', 'warning')
        return redirect(url_for('index'))
    q = random.choice(qs)
    return render_template('question.html', mode='practice', question=q, type_labels=TYPE_LABELS, index=1, total=1)

@app.route('/practice/<qid>')
@login_required
def practice_question(qid):
    q = get_question_by_id(qid)
    if not q:
        flash('题目不存在', 'warning')
        return redirect(url_for('index'))
    return render_template('question.html', mode='practice', question=q, type_labels=TYPE_LABELS, index=1, total=1)

@app.route('/exam', methods=['GET', 'POST'])
@login_required
def exam():
    if request.method == 'POST':
        qtype = request.form.get('type', 'all')
        count = int(request.form.get('count', 20))
        duration = int(request.form.get('duration', 60))  # 考试时长分钟
        qs = load_questions()
        if qtype != 'all':
            qs = [q for q in qs if q['type'] == qtype]
        if not qs:
            flash('该类型题库为空', 'warning')
            return redirect(url_for('index'))
        count = min(count, len(qs))
        selected = random.sample(qs, count)
        exam_id = hashlib.md5(str(datetime.utcnow().timestamp()).encode()).hexdigest()[:12]
        session['exam_id'] = exam_id
        session['exam_questions'] = [q['id'] for q in selected]
        session['exam_answers'] = {}
        session['exam_start'] = datetime.utcnow().isoformat()
        session['exam_duration'] = duration
        return redirect(url_for('exam_question', idx=0))
    return render_template('exam_setup.html', type_labels=TYPE_LABELS)

@app.route('/exam/<int:idx>', methods=['GET', 'POST'])
@login_required
def exam_question(idx):
    qids = session.get('exam_questions', [])
    if not qids or idx < 0 or idx >= len(qids):
        return redirect(url_for('exam_result'))
    q = get_question_by_id(qids[idx])
    if not q:
        flash('题目不存在', 'warning')
        return redirect(url_for('index'))
    if request.method == 'POST':
        # save answer
        ua = extract_answer_from_request(q, request.form)
        session['exam_answers'][q['id']] = ua
        session.modified = True
        if request.form.get('action') == 'submit':
            return redirect(url_for('exam_result'))
        # 支持跳转任意题号
        next_idx = request.form.get('jump_idx', '')
        if next_idx != '' and next_idx.isdigit():
            return redirect(url_for('exam_question', idx=int(next_idx)))
        return redirect(url_for('exam_question', idx=idx+1))
    saved = session.get('exam_answers', {}).get(q['id'], [])
    # 检查是否已超时
    start_iso = session.get('exam_start')
    duration = session.get('exam_duration', 60)
    elapsed = 0
    if start_iso:
        try:
            start = datetime.fromisoformat(start_iso)
            elapsed = int((datetime.utcnow() - start).total_seconds())
        except Exception:
            pass
    remaining = max(0, duration * 60 - elapsed)
    return render_template('question.html', mode='exam', question=q, type_labels=TYPE_LABELS, index=idx+1, total=len(qids), saved=saved,
                           qids=qids, exam_answers=session.get('exam_answers', {}), remaining=remaining, duration=duration)

@app.route('/exam_result')
@login_required
def exam_result():
    qids = session.get('exam_questions', [])
    answers = session.get('exam_answers', {})
    if not qids:
        return redirect(url_for('index'))
    results = []
    total = 0
    score = 0
    type_stats = {}
    domain_stats = {}
    for qid in qids:
        q = get_question_by_id(qid)
        if not q:
            continue
        ua = answers.get(qid, [])
        s = score_answer(q, ua)
        items_count = len(q['content'].get('items', [])) if q['type'] == 'B1' else 1
        total += items_count
        score += s
        results.append({'question': q, 'user_answer': ua, 'score': s})
        # 统计
        t = q['type']
        type_stats[t] = type_stats.get(t, {'total': 0, 'score': 0})
        type_stats[t]['total'] += items_count
        type_stats[t]['score'] += s
        d = q.get('domain', '未知')
        domain_stats[d] = domain_stats.get(d, {'total': 0, 'score': 0})
        domain_stats[d]['total'] += items_count
        domain_stats[d]['score'] += s
        # 自动记录错题
        if s < items_count:
            # 有错误，记录 mistake
            exists = Bookmark.query.filter_by(user_id=current_user.id, qid=qid, kind='mistake').first()
            if not exists:
                db.session.add(Bookmark(user_id=current_user.id, qid=qid, kind='mistake'))
    # 计算百分比
    type_breakdown = []
    for t, v in type_stats.items():
        pct = round(v['score'] / v['total'] * 100, 1) if v['total'] else 0
        type_breakdown.append({'type': TYPE_LABELS.get(t, t), 'total': v['total'], 'score': v['score'], 'pct': pct})
    domain_breakdown = []
    for d, v in domain_stats.items():
        pct = round(v['score'] / v['total'] * 100, 1) if v['total'] else 0
        domain_breakdown.append({'domain': d, 'total': v['total'], 'score': v['score'], 'pct': pct})
    # save record
    details = json.dumps([{'qid': r['question']['id'], 'score': r['score'], 'ua': r['user_answer']} for r in results], ensure_ascii=False)
    rec = ExamRecord(user_id=current_user.id, mode='exam', score=score, total=total, details=details)
    db.session.add(rec)
    db.session.commit()
    # clear session
    session.pop('exam_id', None)
    session.pop('exam_questions', None)
    session.pop('exam_answers', None)
    session.pop('exam_start', None)
    session.pop('exam_duration', None)
    return render_template('result.html', results=results, score=score, total=total, mode='exam',
                           type_breakdown=type_breakdown, domain_breakdown=domain_breakdown)

@app.route('/submit_practice', methods=['POST'])
@login_required
def submit_practice():
    qid = request.form.get('qid')
    q = get_question_by_id(qid)
    if not q:
        flash('题目不存在', 'warning')
        return redirect(url_for('index'))
    ua = extract_answer_from_request(q, request.form)
    s = score_answer(q, ua)
    items_count = len(q['content'].get('items', [])) if q['type'] == 'B1' else 1
    # 自动记录错题
    if s < items_count:
        exists = Bookmark.query.filter_by(user_id=current_user.id, qid=qid, kind='mistake').first()
        if not exists:
            db.session.add(Bookmark(user_id=current_user.id, qid=qid, kind='mistake'))
    # 保存练习记录
    rec = ExamRecord(user_id=current_user.id, mode='practice', score=s, total=items_count,
                     details=json.dumps([{'qid': qid, 'score': s, 'ua': ua}], ensure_ascii=False))
    db.session.add(rec)
    db.session.commit()
    return render_template('result.html', results=[{'question': q, 'user_answer': ua, 'score': s}], score=s, total=items_count, mode='practice')

@app.route('/api/stats')
@login_required
def api_stats():
    qs = load_questions()
    stats = {}
    for q in qs:
        stats[q['type']] = stats.get(q['type'], 0) + 1
    return jsonify(stats)

# ==================== Bookmarks / Mistakes / Domain Practice ====================

@app.route('/bookmarks')
@login_required
def bookmarks():
    kind = request.args.get('kind', 'favorite')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    bms = Bookmark.query.filter_by(user_id=current_user.id, kind=kind).order_by(Bookmark.created_at.desc()).all()
    qids = [b.qid for b in bms]
    qs = [get_question_by_id(qid) for qid in qids]
    qs = [q for q in qs if q]
    total = len(qs)
    start = (page - 1) * per_page
    end = start + per_page
    page_qs = qs[start:end]
    total_pages = (total + per_page - 1) // per_page if total else 1
    return render_template('bookmarks.html', questions=page_qs, kind=kind, type_labels=TYPE_LABELS,
                           page=page, total_pages=total_pages, total=total, per_page=per_page, domain_labels=DOMAIN_LABELS)

@app.route('/bookmark/<qid>', methods=['POST'])
@login_required
def toggle_bookmark(qid):
    kind = request.form.get('kind', 'favorite')
    bm = Bookmark.query.filter_by(user_id=current_user.id, qid=qid, kind=kind).first()
    if bm:
        db.session.delete(bm)
        db.session.commit()
        return jsonify({'status': 'removed', 'qid': qid, 'kind': kind})
    else:
        db.session.add(Bookmark(user_id=current_user.id, qid=qid, kind=kind))
        db.session.commit()
        return jsonify({'status': 'added', 'qid': qid, 'kind': kind})

@app.route('/domain_practice/<domain>')
@login_required
def domain_practice(domain):
    qs = [q for q in load_questions() if q.get('domain') == domain]
    if not qs:
        flash('该领域暂无题目', 'warning')
        return redirect(url_for('index'))
    q = random.choice(qs)
    return render_template('question.html', mode='practice', question=q, type_labels=TYPE_LABELS, index=1, total=1, domain=domain)

@app.route('/record/<int:rid>')
@login_required
def record_detail(rid):
    rec = ExamRecord.query.get_or_404(rid)
    if rec.user_id != current_user.id and current_user.role != 'admin':
        flash('无权查看', 'danger')
        return redirect(url_for('index'))
    try:
        details = json.loads(rec.details) if rec.details else []
    except Exception:
        details = []
    results = []
    for d in details:
        q = get_question_by_id(d.get('qid'))
        if q:
            results.append({'question': q, 'user_answer': d.get('ua', []), 'score': d.get('score', 0)})
    return render_template('result.html', results=results, score=rec.score, total=rec.total, mode=rec.mode, readonly=True)


@app.cli.command('init')
def init_cmd():
    db.create_all()
    init_users()
    print('数据库已初始化')

with app.app_context():
    db.create_all()
    init_users()

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    host = os.environ.get('BIND_HOST', '127.0.0.1')
    app.run(host=host, port=int(os.environ.get('PORT', 5000)), debug=debug)
