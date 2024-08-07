def util = [:]

pipeline {
    agent any
    parameters {
        string(name: "TAG", defaultValue: "latest", description: "The GeoSlicer base version to add as a tag (ex: v2.2.0).")
        booleanParam(name: "LATEST", defaultValue: true, description: "Select if this image should be tagged as 'latest' as well.")
        choice(name: "PLATFORM", choices: ["Windows", "Linux"], description: "Select the desired Operational System to generate the application.")
    }
    options {
            skipDefaultCheckout() 
            throttle(['development'])
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
                        stage('Build & Push [Windows]') {
                            options {
                                timeout(time: 120, unit: "MINUTES")
                            }
                            steps {
                                cleanWs()
                                checkout scm
                                script {
                                    def rootDir = pwd()
                                    util = load "${rootDir}/tools/jenkins/util.groovy"
                                    def id = "${env.OCI_DOCKER_REGISTRY_TOKEN_ID}"
                                    def psw = "${env.OCI_DOCKER_REGISTRY_TOKEN_PASSWORD}"
                                    def tag = "${params.TAG}"
                                    def latest = "${params.LATEST}"

                                    util.login_docker_oci_registry(id, psw)
                                    util.build_docker(true)
                                    util.push_docker_image_to_registry(tag, latest)
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
                        stage('Build & Push [Linux]') {
                            steps {
                                cleanWs()
                                checkout scm
                                script {
                                    def rootDir = pwd()
                                    util = load "${rootDir}/tools/jenkins/util.groovy"

                                    def id = "${OCI_DOCKER_REGISTRY_TOKEN_ID}"
                                    def psw = "${OCI_DOCKER_REGISTRY_TOKEN_PASSWORD}"
                                    def tag = "${params.TAG}"
                                    def latest = "${params.LATEST}"

                                    util.login_docker_oci_registry(id, psw)
                                    util.build_docker(true)
                                    util.push_docker_image_to_registry(tag, latest)
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
