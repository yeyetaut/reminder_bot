import os
import glob
import re

TEST_DIR = "tests"
files = glob.glob(f"{TEST_DIR}/*.py")

for fpath in files:
    with open(fpath, "r") as f:
        content = f.read()

    # Model initializations
    content = re.sub(r'Task\(', r'Task(user_id=1, ', content)
    content = re.sub(r'Project\(', r'Project(user_id=1, ', content)
    content = re.sub(r'ProcessedSource\(', r'ProcessedSource(user_id=1, ', content)

    # Repository calls
    content = re.sub(r'repo\.get_by_id\(([^,)]+)\)', r'repo.get_by_id(1, \1)', content)
    content = re.sub(r'task_repo\.get_by_id\(([^,)]+)\)', r'task_repo.get_by_id(1, \1)', content)
    content = re.sub(r'proj_repo\.get_by_id\(([^,)]+)\)', r'proj_repo.get_by_id(1, \1)', content)
    
    content = re.sub(r'repo\.get_by_source_id\(([^,)]+)\)', r'repo.get_by_source_id(1, \1)', content)
    content = re.sub(r'task_repo\.exists_by_source_id\(([^,)]+)\)', r'task_repo.exists_by_source_id(1, \1)', content)
    content = re.sub(r'repo\.exists_by_source_id\(([^,)]+)\)', r'repo.exists_by_source_id(1, \1)', content)

    content = re.sub(r'repo\.for_date\(([^,)]+)\)', r'repo.for_date(1, \1)', content)
    content = re.sub(r'task_repo\.for_date\(([^,)]+)\)', r'task_repo.for_date(1, \1)', content)
    
    content = re.sub(r'repo\.get_or_create\(([^,)]+)\)', r'repo.get_or_create(1, \1)', content)
    
    content = re.sub(r'repo\.is_already_planned\(([^,)]+)\)', r'repo.is_already_planned(1, \1)', content)
    content = re.sub(r'project_repo\.is_already_planned\(([^,)]+)\)', r'project_repo.is_already_planned(1, \1)', content)
    
    content = re.sub(r'repo\.cleanup_old_tasks\(\)', r'repo.cleanup_old_tasks(1)', content)
    
    content = re.sub(r'repo\.save_many\(([^,)]+)\)', r'repo.save_many(1, \1)', content)
    
    content = re.sub(r'repo\.list_unconfirmed\(\)', r'repo.list_unconfirmed(1)', content)

    # Function calls
    content = re.sub(r'exams_overview\(task_repo\)', r'exams_overview(1, task_repo)', content)
    content = re.sub(r'morning_digest\(task_repo, project_repo\)', r'morning_digest(1, task_repo, project_repo)', content)
    content = re.sub(r'_filter_new\(([^,]+), task_repo, project_repo\)', r'_filter_new(1, \1, task_repo, project_repo)', content)
    content = re.sub(r'_is_duplicate_project\(([^,]+), project_repo\)', r'_is_duplicate_project(1, \1, project_repo)', content)
    content = re.sub(r'get_morning_digest_buttons\(task_repo, project_repo\)', r'get_morning_digest_buttons(1, task_repo, project_repo)', content)

    with open(fpath, "w") as f:
        f.write(content)
