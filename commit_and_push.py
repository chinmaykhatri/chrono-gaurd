import subprocess
import os
import sys

def get_changed_files():
    status_raw = subprocess.check_output(['git', 'status', '--porcelain'], text=True)
    lines = [l.strip() for l in status_raw.splitlines() if l.strip()]
    files = []
    for line in lines:
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            path = parts[1].strip('"')
            if any(forbidden in path for forbidden in ['.hallmark', '.freebuff', 'scratch/']):
                continue
            if os.path.exists(path):
                if os.path.isdir(path):
                    for root, _, fnames in os.walk(path):
                        for fn in fnames:
                            fp = os.path.join(root, fn).replace('\\', '/')
                            if not any(f in fp for f in ['.hallmark', '.freebuff', 'scratch/']):
                                files.append(fp)
                else:
                    files.append(path.replace('\\', '/'))
    return files

def generate_commit_message(filepath):
    parts = filepath.split('/')
    filename = parts[-1]
    
    if filepath == '.gitignore':
        return 'chore(git): update gitignore patterns'
    elif 'verifier/app/pipeline' in filepath:
        name = os.path.splitext(filename)[0]
        return f'feat(verifier): enhance pipeline component {name}'
    elif 'verifier/app/schemas' in filepath:
        return f'feat(verifier): update schema contracts {filename}'
    elif 'verifier/app/scoring' in filepath:
        return f'feat(verifier): refine scoring logic in {filename}'
    elif 'verifier/app' in filepath:
        name = os.path.splitext(filename)[0]
        return f'feat(verifier): update verifier core module {name}'
    elif 'verifier/tests' in filepath:
        name = os.path.splitext(filename)[0]
        return f'test(verifier): add tests for {name}'
    elif 'verifier/migrations' in filepath:
        return f'feat(db): add database migration {filename}'
    elif 'verifier/' in filepath:
        return f'chore(verifier): update verifier build file {filename}'
    elif 'bifrost/plugins/chronoguard' in filepath:
        return f'feat(gateway): implement gateway plugin {filename}'
    elif 'bifrost' in filepath:
        return f'feat(gateway): configure bifrost integration {filename}'
    elif 'console/src/pages' in filepath:
        name = os.path.splitext(filename)[0]
        return f'feat(console): add console page component {name}'
    elif 'console/src/components' in filepath:
        name = os.path.splitext(filename)[0]
        return f'feat(console): add UI component {name}'
    elif 'console/src' in filepath:
        return f'feat(console): update console application {filename}'
    elif 'console/' in filepath:
        return f'chore(console): update console build and configuration {filename}'
    elif 'eval/' in filepath:
        return f'eval(benchmark): update evaluation assets and reports {filename}'
    elif 'scripts/' in filepath:
        return f'tool(scripts): update operational script {filename}'
    elif 'deploy/' in filepath:
        return f'deploy(infra): configure deployment manifest {filename}'
    elif 'docs/' in filepath:
        name = os.path.splitext(filename)[0]
        return f'docs(spec): update documentation {name}'
    elif '.github/' in filepath:
        return f'ci(github): add workflow {filename}'
    elif filename.endswith('.md'):
        return f'docs: update {filename}'
    elif filename.endswith('.yaml') or filename.endswith('.yml'):
        return f'chore(config): update configuration {filename}'
    else:
        return f'chore: update {filename}'

def main():
    files = get_changed_files()
    print(f"Discovered {len(files)} files to commit one by one.")
    
    # Process commit one by one
    committed = 0
    for i, fp in enumerate(files, 1):
        # Stage the single file
        subprocess.run(['git', 'add', fp], check=True)
        msg = generate_commit_message(fp)
        commit_res = subprocess.run(['git', 'commit', '-m', msg], capture_output=True, text=True)
        if commit_res.returncode == 0:
            committed += 1
            print(f"[{i}/{len(files)}] Committed {fp} -> {msg}")
        else:
            print(f"[{i}/{len(files)}] Skipped (no diff or error) {fp}")
            
    print(f"\nSuccessfully created {committed} individual commits!")

if __name__ == '__main__':
    main()
