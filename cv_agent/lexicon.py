"""Từ điển viết tay cho baseline. Bổ sung không cần sửa code:
tạo file lexicon_user.json (hoặc đặt biến CV_AGENT_LEXICON=đường_dẫn) dạng

  {"implies": {"zalo ads": "quảng cáo ads"},
   "field_groups": [["điều dưỡng", "y khoa", "y tá"]],
   "stop": ["công_ty"],
   "tech_aliases": {"c\\+\\+": "cpp"}}
"""
import json
import os
import re
import sys
from pathlib import Path

# Từ dừng ĐƠN (một âm tiết/một từ). Không đưa âm tiết của từ ghép vào đây (vd "kỹ", "hợp", "kinh").
STOP = set("""có và hoặc các của cho với ở trong về là được khi để một những như biết hiểu rất khá nhiều thêm
này đó nên cần phải ra vào cũng hay nữa tại bằng từ đến tới trên hơn năm chạy
the and or of in with to a an at least year years experience exp strong good knowledge familiar
familiarity proficient proficiency working ability skill skills degree plus using use have has
be is are for on as by from etc including include related relevant solid excellent minimum command""".split())

# Cụm từ dừng (khớp liền nhau theo âm tiết)
STOP_PHRASES = ["thành thạo", "nắm vững", "kinh nghiệm", "ưu tiên", "ứng viên", "yêu cầu", "sử dụng",
                "làm việc", "kỹ năng", "hiện hành", "tham gia", "phối hợp", "ít nhất", "tối thiểu", "vị trí",
                "lĩnh vực", "chuyên ngành", "khả năng", "liên quan", "am hiểu", "có thể", "thực hiện",
                "tốt nghiệp", "trình độ"]

OR_WORDS = {"hoặc", "or", "hay"}

# Từ viết tắt 2 chữ cái vẫn là thuật ngữ kỹ thuật
SHORT_LATIN = {"ai", "ml", "qa", "qc", "hr", "ui", "ux", "bi", "pr", "bd"}

# Viết lại thuật ngữ có ký tự đặc biệt trước khi bỏ dấu câu: (regex, thay thế)
TECH_ALIASES = [
    (r"c\+\+", "cpp"), (r"c#", "csharp"), (r"asp\.net|\.net\b", "dotnet"), (r"node\.?js", "nodejs"),
    (r"vue\.?js", "vuejs"), (r"react\.?js", "react"), (r"next\.?js", "nextjs"), (r"ci\s*/\s*cd", "cicd"),
    (r"power\s*bi", "powerbi"), (r"(?:microsoft|ms)\s*office", "msoffice"), (r"a\s*/\s*b\s*test(?:ing)?", "abtest"),
    (r"google\s*analytics", "google analytics"),
    # cách viết tắt / viết khác hay gặp trong CV
    (r"\bk8s\b", "kubernetes"), (r"scikit[\s\-_]*learn|\bsklearn\b", "scikit learn"), (r"\bpostgres\b", "postgresql"),
    (r"\bjs\b", "javascript"), (r"\bts\b", "typescript"), (r"\b(?:ms\s*sql|mssql)\b", "sql server"),
    (r"(?:microsoft|ms)\s*excel", "excel"), (r"(?:microsoft|ms)\s*word", "word"), (r"(?:microsoft|ms)\s*powerpoint", "powerpoint"),
    (r"\bg(?:oogle)?\s*sheets?\b", "google sheets"), (r"\bgpt[\s\-]*\d(?:\.\d)?\b", "gpt"), (r"yolo\s*v?\d+", "yolo"),
    (r"\bobject[\s\-]*oriented\b", "oop"), (r"\bvector\s*(?:db|database|store)s?\b", "vector database"),
]

# Nếu dòng CV có cụm bên trái thì coi như có cả các từ bên phải (bổ sung được qua lexicon_user.json)
IMPLIES = {
    "pytest": "python unit test", "api": "backend",
    "pandas": "python", "numpy": "python",
    "tensorflow": "machine learning deep learning", "pytorch": "machine learning deep learning",
    "spring": "java backend", "laravel": "php backend", "nodejs": "javascript backend",
    "react": "frontend javascript", "vuejs": "frontend javascript", "angular": "frontend javascript",
    "postgresql": "sql cơ sở dữ liệu", "mysql": "sql cơ sở dữ liệu", "sql server": "sql cơ sở dữ liệu",
    "sql": "cơ sở dữ liệu", "mongodb": "cơ sở dữ liệu nosql",
    "kubernetes": "container docker triển khai",
    "aws": "cloud triển khai", "gcp": "cloud triển khai", "azure": "cloud triển khai",
    "looker": "bi dashboard báo cáo",
    "facebook ads": "quảng cáo ads", "google ads": "quảng cáo ads", "tiktok ads": "quảng cáo ads",
    "ads": "quảng cáo", "quảng cáo": "ads", "roas": "quảng cáo", "cpa": "quảng cáo", "ctr": "quảng cáo",
    "google analytics": "analytics", "seo": "marketing", "sem": "quảng cáo marketing",
    "google sheets": "excel", "pivot table": "excel", "vlookup": "excel",
    "misa": "phần mềm kế toán", "fast accounting": "phần mềm kế toán", "bravo": "phần mềm kế toán",
    "sap": "erp", "erp": "phần mềm quản lý",
    "ielts": "tiếng anh english", "toeic": "tiếng anh english", "toefl": "tiếng anh english",
    "english": "tiếng anh", "tiếng anh": "english",
    "recruitment": "tuyển dụng", "recruiter": "tuyển dụng", "headhunt": "tuyển dụng",
    "tuyển dụng": "recruitment", "topcv": "tuyển dụng", "vietnamworks": "tuyển dụng",
    "sales": "bán hàng kinh doanh", "bán hàng": "sales", "customer service": "chăm sóc khách hàng",
    "chăm sóc khách hàng": "customer service", "cskh": "chăm sóc khách hàng customer service",
    "kế toán tổng hợp": "kế toán", "kế toán thanh toán": "kế toán", "kế toán thuế": "kế toán thuế",
    "kế toán trưởng": "kế toán", "kiểm toán viên": "kiểm toán",
    # --- AI / ML / dữ liệu / phần mềm
    "git": "version control", "github": "version control git", "gitlab": "version control git",
    "bitbucket": "version control git", "svn": "version control",
    "keras": "machine learning deep learning", "ml": "machine learning học máy",
    "rnn": "neural networks deep learning",
    "bert": "nlp transformers", "phobert": "nlp transformers", "llm": "nlp transformers", "hugging face": "nlp transformers",
    "resnet": "cnn computer vision", "yolo": "cnn computer vision", "opencv": "computer vision", "vision": "computer vision",
    "xgboost": "machine learning statistical modeling", "random forest": "machine learning statistical modeling",
    "regression": "statistical modeling machine learning", "statistics": "statistical modeling",
    "scikit learn": "machine learning python statistical modeling",
    "mlflow": "mlops", "kubeflow": "mlops", "airflow": "mlops", "github actions": "cicd", "jenkins": "cicd",
    "gitlab ci": "cicd", "cicd": "mlops", "spark": "distributed systems", "hadoop": "distributed systems",
    "kafka": "distributed systems", "matplotlib": "data visualization", "seaborn": "data visualization",
    "powerbi": "data visualization bi dashboard báo cáo", "tableau": "data visualization bi dashboard báo cáo",
    "fastapi": "python backend api deployment", "flask": "python backend api deployment", "django": "python backend api deployment",
    "docker": "container triển khai deployment", "code review": "software engineering",
    "unit test": "test software engineering",
    # --- song ngữ Việt <-> Anh: JD tiếng Việt thường gặp CV tiếng Anh (và ngược lại)
    "project": "dự án", "projects": "dự án", "dự án": "project", "internship": "thực tập intern", "intern": "thực tập",
    "thực tập": "intern internship", "machine learning": "ml học máy", "học máy": "machine learning ml",
    "deep learning": "neural networks machine learning học sâu", "học sâu": "deep learning",
    "nlp": "xử lý ngôn ngữ tự nhiên natural language processing", "xử lý ngôn ngữ tự nhiên": "nlp",
    "computer vision": "thị giác máy tính", "thị giác máy tính": "computer vision",
    "neural network": "mạng neural deep learning machine learning", "neural networks": "mạng neural", "mạng neural": "neural networks",
    "cnn": "neural networks mạng neural deep learning", "lstm": "neural networks mạng neural deep learning",
    "transformer": "neural networks mạng neural deep learning nlp", "transformers": "neural networks mạng neural deep learning nlp",
    "python": "lập trình programming", "java": "lập trình programming", "javascript": "lập trình programming",
    "cpp": "lập trình programming", "golang": "lập trình programming", "csharp": "lập trình programming",
    "rag": "llm nlp retrieval", "algorithm": "thuật toán", "algorithms": "thuật toán", "thuật toán": "algorithms",
    "artificial intelligence": "ai trí tuệ nhân tạo", "trí tuệ nhân tạo": "ai artificial intelligence",
    # --- công cụ AI/ML hay gặp trong CV fresher
    "typescript": "javascript lập trình programming", "pyspark": "spark python distributed systems", "scipy": "python",
    "jupyter": "python", "colab": "python", "kaggle": "machine learning", "tensorboard": "machine learning deep learning",
    "spacy": "nlp", "nltk": "nlp", "gensim": "nlp", "gpt": "llm nlp transformers", "openai": "llm nlp", "chatgpt": "llm nlp",
    "langchain": "llm rag nlp transformers", "llamaindex": "llm rag nlp", "vector database": "rag retrieval",
    "faiss": "vector database rag retrieval", "chromadb": "vector database rag retrieval", "pinecone": "vector database rag retrieval",
    "sagemaker": "cloud aws mlops triển khai", "vertex ai": "cloud gcp mlops triển khai", "azure ml": "cloud azure mlops triển khai",
    "onnx": "deployment triển khai", "tensorrt": "deployment triển khai", "streamlit": "python deployment", "gradio": "python deployment",
    "wandb": "mlops", "dvc": "mlops version control", "docker compose": "docker container triển khai",
    "restful": "api backend", "graphql": "api backend", "postman": "api", "redis": "cơ sở dữ liệu backend", "sqlite": "sql cơ sở dữ liệu",
    "elasticsearch": "cơ sở dữ liệu",
    "data structures": "algorithms thuật toán", "cấu trúc dữ liệu": "data structures algorithms thuật toán", "giải thuật": "algorithms thuật toán",
    "oop": "lập trình hướng đối tượng programming", "lập trình hướng đối tượng": "oop programming",
}

# Nhóm ngành học tương đương (so khớp theo cụm)
FIELD_GROUPS = [
    ["công nghệ thông tin", "khoa học máy tính", "kỹ thuật phần mềm", "hệ thống thông tin", "an toàn thông tin",
     "khoa học dữ liệu", "trí tuệ nhân tạo", "học máy", "computer science", "software engineering", "information technology",
     "artificial intelligence", "machine learning", "data science", "tin học"],
    ["kế toán", "kiểm toán", "tài chính", "ngân hàng", "accounting", "finance", "auditing"],
    ["kinh tế", "tài chính", "quản trị kinh doanh", "thương mại", "kinh doanh", "economics", "business administration"],
    ["marketing", "truyền thông", "quan hệ công chúng", "thương mại điện tử", "quảng cáo", "communications", "advertising"],
    ["quản trị nhân sự", "quản trị nguồn nhân lực", "quản trị nhân lực", "nhân sự", "nhân lực", "tâm lý", "luật", "quản trị kinh doanh", "human resource"],
    ["thống kê", "toán", "toán ứng dụng", "khoa học dữ liệu", "statistics", "mathematics", "data science"],
    ["điện", "điện tử", "tự động hoá", "cơ điện tử", "electrical", "electronics"],
]

# Từ kỹ thuật nhận diện được ngay cả khi CV không dấu (dùng cho chế độ không dấu)
EXTRA_TECH = set("""excel word powerpoint python java javascript sql git docker aws misa sap erp tableau powerbi
facebook google tiktok seo sem ads roas cpa ctr crm html css react php golang kotlin swift flutter linux jira
acca cpa ielts toeic topcv vietnamworks linkedin photoshop figma autocad git sap seo sem mac api""".split())


def _warn(message: str) -> None:
    print(f"[cv_agent] {message}", file=sys.stderr)


def _user_lexicon_path():
    """CV_AGENT_LEXICON, hoặc lexicon_user.json ở thư mục đang chạy, hoặc ở thư mục gốc của dự án."""
    if os.getenv("CV_AGENT_LEXICON"):
        return Path(os.environ["CV_AGENT_LEXICON"])
    for candidate in (Path("lexicon_user.json"), Path(__file__).resolve().parent.parent / "lexicon_user.json"):
        if candidate.is_file():
            return candidate
    return None


def _load_user():
    """Từ điển bổ sung do người dùng viết. File hỏng (JSON sai, sai kiểu) chỉ bị bỏ qua kèm cảnh báo, không được làm sập cả chương trình."""
    path = _user_lexicon_path()
    if path is None:
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        implies = {str(k).lower(): str(v) for k, v in dict(data.get("implies", {})).items()}
        groups = [[str(x) for x in g] for g in data.get("field_groups", [])]
        stop = [str(x) for x in data.get("stop", [])]
        stop_phrases = [str(x) for x in data.get("stop_phrases", [])]
        aliases = [(str(k), str(v)) for k, v in dict(data.get("tech_aliases", {})).items()]
        for pattern, _ in aliases:
            re.compile(pattern)                                  # regex sai thì bỏ cả file, không nạp dở dang
    except (OSError, ValueError, TypeError, AttributeError, re.error) as e:
        _warn(f"Bỏ qua từ điển người dùng {path}: {type(e).__name__}: {e}")
        return
    IMPLIES.update(implies)
    FIELD_GROUPS.extend(groups)
    STOP.update(stop)
    STOP_PHRASES.extend(stop_phrases)
    TECH_ALIASES.extend(aliases)


_load_user()
TECH_ALIASES_C = [(re.compile(p, re.I), r) for p, r in TECH_ALIASES]
# Một biểu thức gộp để kiểm tra nhanh: đa số dòng CV không chứa cách viết nào cần đổi, nên chỉ cần một lần tìm thay vì mấy chục lần thay thế
TECH_ANY = re.compile("|".join(f"(?:{p})" for p, _ in TECH_ALIASES), re.I)
