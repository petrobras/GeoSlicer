def util = [:]

pipeline {
    agent any
    parameters {
        booleanParam(name: 'TEST', defaultValue: true, description: 'Allow to run and check the integration tests.')
        booleanParam(name: 'EXPORT', defaultValue: true, description: 'Allow to export the generated application to the OCI bucket.')
        booleanParam(name: 'SFX', defaultValue: false, description: 'Create Self-Extracting File instead of the compressed file.')
        booleanParam(name: 'PUBLIC_VERSION', defaultValue: false, description: 'Generate the application\'s public version.')
        booleanParam(name: 'NO_PUBLIC_COMMIT', defaultValue: true, description: 'Avoid commiting to the opensource code repository. (only valid when enabling the public version generation parameter)')        
        choice(name: 'PLATFORM', choices: ['Linux', 'Windows'], description: 'Select the desired Operational System to generate the application.')
        string(name: 'BASE', defaultValue: 'latest', description: 'Filename of the base archive or version number. "latest" will download the latest version from the OCI bucket.')
    }
    options {
            skipDefaultCheckout() 
            throttle(['release'])
    }
    environment {
        OCI_DOCKER_REGISTRY_TOKEN_ID     = credentials("oci_docker_registry_token_id")
        OCI_DOCKER_REGISTRY_TOKEN_PASSWORD = credentials("oci_docker_registry_token_password")
    }
    stages {
        stage('Start') {
            options {
                skipDefaultCheckout()
            }
            when { 
                beforeAgent true;
                triggeredBy cause: 'UserIdCause'
            }
            failFast true
            stages {
                stage("Check requirements") {
                    agent {
                        label "${PLATFORM}".toLowerCase()
                    }
                    options {
                        timeout(time: 10, unit: "MINUTES")
                        skipDefaultCheckout()
                    }
                    steps {
                        cleanWs()
                        checkout scm
                        script {
                            def rootDir = pwd()
                            util = load "${rootDir}/tools/jenkins/util.groovy"

                            // Check Test & Export variables
                            if (("${params.TEST}" == "false") && ("${params.EXPORT}" == "false")) {
                                error("If you don't want to test and don't want to deploy the application, then there is nothing to do.")
                            }

                            // Check git tag related to current branch
                            def git_tag = util.get_git_tag()
                            println("Checking current git tag ${git_tag}...")
                            if (git_tag == null || git_tag.allWhitespace) {
                                error("This branch commit is not related to a tag. Please create a git tag in this branch before starting the process.")
                            }

                            // Check if branch name is related to a valid branch
                            def branch_name = util.get_branch_name()
                            util.check_branch_name("${branch_name} 'master' 'release' 'hotfix'")
                        }
                    }
                }
                stage("Windows") {
                    when { 
                        beforeAgent true;
                        anyOf {
                                expression { return "${params.PLATFORM}" == "Windows"; }
                        }
                    }
                    agent {
                            label "windows"
                    }
                    options { skipDefaultCheckout() }
                    environment {
                        PIP_DEFAULT_TIMEOUT = 300
                    }
                    stages {
                        stage('Generate & Test & Export [Windows]') {
                            options {
                                timeout(time: 600, unit: "MINUTES")
                            }
                            steps {
                                script {
                                    def git_tag = util.get_git_tag()                                    
                                    def no_test_flag = ("${params.EXPORT}" == "false") ? "--no-export" : ""
                                    def no_export_flag = ("${params.TEST}" == "false") ? "--no-test" : ""
                                    def sfx_flag = ("${params.SFX}" == "true") ? "--sfx" : ""
                                    def public_flag = ("${params.PUBLIC_VERSION}" == "true") ? "--generate-public-version" : ""
                                    def no_public_commit_flag = ("${params.NO_PUBLIC_COMMIT}" == "true") ? "--no-public-commit" : ""
                                    def base = "${params.BASE}"
                                    if (base.trim().isEmpty()) {
                                        error("Base is empty. Please, set the base parameter.")
                                    }
                                    def arguments = "--version ${git_tag} --no-gpu ${no_test_flag} ${no_export_flag} ${sfx_flag} ${public_flag} ${no_public_commit_flag} --base ${base} --production".trim()
                                    util.download_and_deploy(arguments, false)
                                }
                            }
                        }
                    }
                }
                stage("Linux") {  
                    when { 
                        beforeAgent true;
                        anyOf {
                                expression { return "${params.PLATFORM}" == "Linux"; }
                        }
                    }          
                    agent {
                            label "linux"
                    }
                    options { skipDefaultCheckout() }
                    environment {
                        PIP_DEFAULT_TIMEOUT = 300
                    }
                    stages {
                        stage('Build [Linux]') {
                            options {
                                timeout(time: 90, unit: "MINUTES")
                            }
                            steps {
                                script {
                                    def rootDir = pwd()
                                    def id = "${OCI_DOCKER_REGISTRY_TOKEN_ID}"
                                    def psw = "${OCI_DOCKER_REGISTRY_TOKEN_PASSWORD}"
                                    util = load "${rootDir}/tools/jenkins/util.groovy"
                                    util.login_docker_oci_registry(id, psw)
                                    util.build_docker()
                                }
                            }
                            post {
                                always {
                                    script {
                                        util.run_docker_prune()                          
                                    }
                                }
                            }
                        }
                        stage('Generate & Test & Export [Linux]') {
                            steps {
                                script {
                                    def git_tag = util.get_git_tag()
                                    def no_test_flag = ("${params.EXPORT}" == "false") ? "--no-export" : ""
                                    def no_export_flag = ("${params.TEST}" == "false") ? "--no-test" : ""
                                    def sfx_flag = ("${params.SFX}" == "true") ? "--sfx" : ""
                                    def public_flag = ("${params.PUBLIC_VERSION}" == "true") ? "--generate-public-version" : ""
                                    def no_public_commit_flag = ("${params.NO_PUBLIC_COMMIT}" == "true") ? "--no-public-commit" : ""
                                    def base = "${params.BASE}"
                                    if (base.trim().isEmpty()) {
                                        error("Base is empty. Please, set the base parameter.")
                                    }
                                    def arguments = "--version ${git_tag} --no-gpu ${no_test_flag} ${no_export_flag} ${sfx_flag} ${public_flag} ${no_public_commit_flag} --base ${base} --production".trim()
                                    util.download_and_deploy(arguments, true)
                                }
                            }
                            post {
                                always {
                                    script {
                                        util.docker_compose_down()
                                    }
                                }
                            }
                        }
                    }
                }
            }
            post {
                // Clean after build
                always {
                    cleanWs(cleanWhenNotBuilt: false,
                            deleteDirs: true,
                            disableDeferredWipeout: true,
                            notFailBuild: true,
                            patterns: [[pattern: '.gitignore', type: 'INCLUDE'],
                                    [pattern: '.propsfile', type: 'EXCLUDE']])
                }
            }
        }
    }
}
