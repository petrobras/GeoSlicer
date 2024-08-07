def get_platform() {
    if (isUnix()) {
        return "linux"
    } 

    return "windows"
}


def get_docker_image_label(base=false) {
    def platform = get_platform()
    def docker_image_label = ""
    if (base == true) {
        docker_image_label = (platform == "linux") ? "slicerltrace-base-linux" : "slicerltrace-base-windows"
    }
    else {
        docker_image_label = (platform == "linux") ? "slicerltrace-linux" : "slicerltrace-windows"
    }
    
    return docker_image_label
}


def run_docker_prune() {
    try {
        println("Cleaning dangling docker related files...")
        run_script("docker system prune --force --filter 'until=3h'")
        run_script("docker volume prune --force")
        run_script("docker logout")
    } catch (Exception err) {
        println("Unable to execute docker command: ${err}")
    }    
}


def run_static_analysis_process() {
    println("Starting code static analysis process!")
    println("1) Running black...")
    def docker_image_label = get_docker_image_label()
    run_script("docker-compose run --rm -T --entrypoint 'python -m black --check .' ${docker_image_label}")

    println("2) Running line ending checker...")
    run_script("docker-compose run --rm -T --entrypoint 'sh ./tools/pipeline/check_line_endings.sh' ${docker_image_label}")

    println("3) Running licenses checker...")
    run_script("docker-compose run --rm -T --entrypoint 'sh ./tools/pipeline/check_dependencies_licenses.sh' ${docker_image_label}")
}


def run_unit_test_process(use_docker=true) {
    println("Running unit test process...")

    if (use_docker == true) {
        def docker_image_label = get_docker_image_label()
        run_script("docker-compose run --rm -T --entrypoint 'python -m pytest -sv' ${docker_image_label}")
    } else {
        run_script("python -m pytest -sv")
    }
}


def push_docker_image_to_registry(tag, latest) {
    if (!tag) {
        error("Missing the tag information.")
    }

    def docker_image_label = get_docker_image_label(true)
    def platform = get_platform()

    run_script("docker tag ${docker_image_label} gru.ocir.io/grrjnyzvhu1t/slicerltrace/${platform}:${tag}")
    run_script("docker push gru.ocir.io/grrjnyzvhu1t/slicerltrace/${platform}:${tag}")
    assert_last_exit_code("Failed to upload image with tag ${tag} into the OCI Container Registry.")

    if (latest == "true") {
        run_script("docker tag ${docker_image_label} gru.ocir.io/grrjnyzvhu1t/slicerltrace/${platform}:latest")
        run_script("docker push gru.ocir.io/grrjnyzvhu1t/slicerltrace/${platform}:latest")
        assert_last_exit_code("Failed to upload image with tag ${tag} into the OCI Container Registry.")
    }
}

def login_docker_oci_registry(id, psw) {
    """ Wrapper to execute docker login.
        Using the string interpolation below trigger a warning due it being insecure.
        (See https://jenkins.io/redirect/groovy-string-interpolation).
        But using the recommended approach fails to work in a Windows environment.
    """
    run_script("docker login gru.ocir.io -u '${id}' -p '${psw}'") 
    assert_last_exit_code("Failed to login at the OCI Container Registry.")
}

def build_docker(base=false) {
    def platform = get_platform()
    println("Building docker for ${platform}...")
    
    def docker_image_label = get_docker_image_label(base)
    
    if (!docker_image_label) {
        error("Couldn't find a target docker compose service for platform ${platform}")
    }

    println("Target docker compose service: ${docker_image_label}")
    run_script("docker-compose build ${docker_image_label}")
    assert_last_exit_code("Failed to build docker service '${docker_image_label}'.")
}

def _execute_generate_test_deploy_script(String arguments) {
    def docker_image_label = get_docker_image_label()
    println("Starting script to download, deploy and test the application inside the '${docker_image_label}' docker service, with the following arguments: ${arguments}...")
    run_script("docker-compose up -d ${docker_image_label}")
    run_script("docker-compose exec -T ${docker_image_label} git config --unset core.hooksPath")
    run_script("docker-compose exec -T ${docker_image_label} git lfs install")
    run_script("docker-compose exec -T ${docker_image_label} python ./tools/pipeline/generate_test_deploy.py ${arguments}")
    assert_last_exit_code("Failed to execute script to download, deploy and test the application.")
}

def download_and_deploy(String arguments, boolean use_docker) {
    def last_error_code_var = get_last_exit_code_var()
    def platform = get_platform()
    if (use_docker == true) {
        if (platform == "linux") {
            wrap([$class: 'Xvnc', takeScreenshot: false, useXauthority: true]) {
                _execute_generate_test_deploy_script(arguments)
            }
        } else {
            _execute_generate_test_deploy_script(arguments)
        }
        return
    }

    println("Starting script to download, deploy and test the application with the following arguments: ${arguments}...")

    run_script("git submodule update --init --recursive")
    run_script("git-bash ./tools/install_packages.sh") 
    run_script("python ./tools/pipeline/generate_test_deploy.py ${arguments} --avoid-long-path")
    assert_last_exit_code("Failed to execute script to download, deploy and test the application.")
}

def execute_ui_test(String arguments) {
    
    println("Starting script to download, deploy and test the application with the following arguments: ${arguments}...")
    
    run_script("git submodule update --init --recursive")
    run_script("python ./tools/pipeline/generate_test_deploy.py ${arguments}")
    assert_last_exit_code("Failed to execute script to download, deploy and test the application.")
}


def docker_compose_down() {
    print("Shutting docker service down...")
    run_script("docker-compose down --remove-orphans -v")
}


def get_branch_name() {
    platform = get_platform()
    if (platform == "linux") {
        return "${BRANCH_NAME}"
    } else if (platform == "windows") {
        return "${env:BRANCH_NAME}"
    }
     
    throw new Exception("Platform ${platform} not implemented yet.")
}   


def check_branch_name(arguments) {
    println("Checking if the branch source is valid...")
    def platform = get_platform()
    def error_code_var = get_last_exit_code_var()
    if (platform == "linux") {
        run_script("./tools/pipeline/check_branch_root.sh ${arguments}")
    } else if (platform == "windows") {
        run_script("& \$env:bash ./tools/pipeline/check_branch_root.sh ${arguments}")
    } else {
        throw new Exception("Platform ${platform} not implemented yet.")
    }

    assert_last_exit_code("The script detected the current branch name is not valid!")
}


def get_git_tag(platform="linux") {
    return run_script('echo "$(git tag -l --points-at HEAD)"')
}   


def run_script(command) {
    def platform = get_platform()
    def platform_shell = (platform == "linux") ? this.&sh : this.&powershell
    println("Running command: ${command}")
    if (platform != "linux") {
        command = 'Invoke-Command {\$ErrorActionPreference = "SilentlyContinue" ; ' + command + ' }'
    }
    return platform_shell(returnStdout: true, script: "${command}").trim()
}


def assert_last_exit_code(error_message) {   
    def platform = get_platform()
    def last_error_code_var = get_last_exit_code_var()
    def error_code = run_script("echo \"${last_error_code_var}\"")

    if (((platform == "linux") && (error_code != "0")) || ((platform == "windows") && (error_code != "True"))) {
        if (!error_message) {
            error_message = "A script execution has failed. Please check the logs."
        }
        error("${error_message} - Error code: ${error_code}")
    }
}


def get_last_exit_code_var() {
    // Requesting $LASTEXITCODE for Windows powershell isn't working as it should
    // so we're using $? for every OS at the moment.
    return "\$?"
}


def get_exported_application_name(mode, version) {
    if (mode == "Production") {
        return "GeoSlicer-${version}"
    }

    return "GeoSlicer-<date>_development"
}


def notify_slack(message, url) {
    def platform = get_platform()
    if (platform == "linux") {
        run_script("""curl --silent -X POST -H 'Content-type: application/json' --data '{"text":"${message}"}' ${url}""")
    } else if (platform == "windows") {
        run_script("""
            \$body = @{ text = '${message}' } | ConvertTo-Json
            \$bodyBytes = [System.Text.Encoding]::UTF8.GetBytes(\$body)
            \$bodyEncoded = [System.Text.Encoding]::UTF8.GetString(\$bodyBytes)
            Invoke-RestMethod -Uri '${url}' -Method Post -Headers \$headers -Body \$bodyEncoded -ContentType 'application/json; charset=utf-8' > \$null 2>&1
        """)
    }
}

return this;