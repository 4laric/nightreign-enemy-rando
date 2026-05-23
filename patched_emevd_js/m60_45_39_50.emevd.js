// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 91005506, 1045395200);
    $InitializeCommonEvent(0, 90005580, 1045391950, 1045390950, 7661);
    $InitializeCommonEvent(0, 90005910, 1045391800, 7686);
    $InitializeCommonEvent(0, 91005505, 1045392510, 7686);
    $InitializeCommonEvent(0, 90065901, 1045394890);
    $InitializeCommonEvent(0, 90015150, 1045390200, 73078);
    $InitializeCommonEvent(0, 90015151, 1045390200, 74038);
    $InitializeCommonEvent(0, 90015152, 1045390200, 74038);
    $InitializeCommonEvent(0, 90005931, 1045390200, 1045391200, 0, 1045391201);
    $InitializeCommonEvent(0, 91005504, 1045391550, 7603, 0, 0, 0);
    $InitializeCommonEvent(0, 91005504, 1045391551, 7600, 7601, 7602, 7605);
    $InitializeCommonEvent(0, 90015140, 1045391210, 200, 9103, 1045398200);
    $InitializeCommonEvent(0, 90015000, 1045392901, 1045390851, 907550002, 30, 756020, 8110);
    $InitializeCommonEvent(0, 99055500, 1045390851, 15);
    $InitializeCommonEvent(0, 90015030, 1045392901, 1045390851, 30, 756020, 8110);
    $InitializeCommonEvent(0, 90015002, 0, 1045392901, 1045390850, 1045390851, 1020, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015160, 1045390850, 1045392901);
    $InitializeCommonEvent(0, 90015161, 1045390850, 1045392900);
    $InitializeCommonEvent(0, 90015162, 1045390850, 1045392900, 1045392901);
    $InitializeCommonEvent(0, 90015163, 1045390851, 1045392900, 1045392901, 1045390850);
    $InitializeCommonEvent(0, 90015164, 1045390850, 1045392901);
    if (MissionActive(403)) {
        $InitializeCommonEvent(0, 90085020, 403, 8411, 8412, 8410, 1045390270, 99850, 1045390270, Hero.Duchess);
        $InitializeCommonEvent(0, 90085021, 403, 8411, 1045392270, 1045390270, Hero.Duchess);
        if (1 == 3) {
            $InitializeCommonEvent(0, 90085002, 403, 8412, 8411, 1045390270, 1045395270, 1045390271, 0, 0, 0, 20032);
        }
        if (2 == 3) {
            $InitializeCommonEvent(0, 90085002, 403, 8412, 8411, 1045390270, 1045395270, 1045390271, 1045390272, 0, 0, 20032);
        }
        if (3 == 3) {
            $InitializeCommonEvent(0, 90085002, 403, 8412, 8411, 1045390270, 1045395270, 1045390271, 1045390272, 1045390273, 0, 20032);
        }
        if (4 == 3) {
            $InitializeCommonEvent(0, 90085002, 403, 8412, 8411, 1045390270, 1045395270, 1045390271, 1045390272, 1045390273, 1045390274, 20032);
        }
        $InitializeCommonEvent(0, 90085016, 403, 8412, 8411, 1045390270, 1045395270, 1030, 3);
        $InitializeCommonEvent(0, 90085022, 403, 8412, 1045392271, 1045390270, 503, Hero.Duchess);
        $InitializeCommonEvent(0, 90085023, 403, 8412, 8410, 1045390270, 6853, 1045390270, Hero.Duchess);
        if (1 == 3) {
            $InitializeCommonEvent(0, 90015000, 8411, 1045390271, 912000050, 30, 0, 8412);
            $InitializeCommonEvent(0, 99055500, 1045390271, 15);
        }
        if (1 != 3) {
            $InitializeCommonEvent(0, 90015000, 8411, 1045395270, 912000050, 30, 0, 8412);
            $InitializeCommonEvent(0, 99055500, 1045395270, 15);
        }
        $InitializeCommonEvent(0, 90015030, 0, 1045395270, 30, 920930, 8412);
    }
    if (MissionActive(803)) {
        $InitializeCommonEvent(0, 90085020, 803, 8511, 8512, 8510, 1045390280, 99852, 1045390280, Hero.Executor);
        $InitializeCommonEvent(0, 90085021, 803, 8511, 1045392280, 1045390280, Hero.Executor);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90085002, 803, 8512, 8511, 1045390280, 1045395280, 1045390281, 0, 0, 0, 20032);
        }
        if (2 == 1) {
            $InitializeCommonEvent(0, 90085002, 803, 8512, 8511, 1045390280, 1045395280, 1045390281, 1045390282, 0, 0, 20032);
        }
        if (3 == 1) {
            $InitializeCommonEvent(0, 90085002, 803, 8512, 8511, 1045390280, 1045395280, 1045390281, 1045390282, 1045390283, 0, 20032);
        }
        if (4 == 1) {
            $InitializeCommonEvent(0, 90085002, 803, 8512, 8511, 1045390280, 1045395280, 1045390281, 1045390282, 1045390283, 1045390284, 20032);
        }
        $InitializeCommonEvent(0, 90085016, 803, 8512, 8511, 1045390280, 1045395280, 1030, 3);
        $InitializeCommonEvent(0, 90085022, 803, 8512, 1045392281, 1045390280, 504, Hero.Executor);
        $InitializeCommonEvent(0, 90085037, 803, 8512, 8510, 1045391280, 9220, Hero.Executor);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90015000, 8511, 1045390281, 912000060, 30, 0, 8512);
            $InitializeCommonEvent(0, 99055500, 1045390281, 15);
        }
        if (1 != 1) {
            $InitializeCommonEvent(0, 90015000, 8511, 1045395280, 912000060, 30, 0, 8512);
            $InitializeCommonEvent(0, 99055500, 1045395280, 15);
        }
        $InitializeCommonEvent(0, 90015030, 0, 1045395280, 30, 920930, 8512);
    }
    if (MissionActive(701)) {
        $InitializeCommonEvent(0, 90085020, 701, 8476, 8477, 8475, 1045390295, 99844, 1045390290, Hero.Recluse);
        $InitializeCommonEvent(0, 90085021, 701, 8476, 1045392290, 1045390290, Hero.Recluse);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90085002, 701, 8477, 8476, 1045390290, 1045395290, 1045390290, 0, 0, 0, 20026);
        }
        if (2 == 1) {
            $InitializeCommonEvent(0, 90085002, 701, 8477, 8476, 1045390290, 1045395290, 1045390290, 1045390291, 0, 0, 20026);
        }
        if (3 == 1) {
            $InitializeCommonEvent(0, 90085002, 701, 8477, 8476, 1045390290, 1045395290, 1045390290, 1045390291, 1045390292, 0, 20026);
        }
        if (4 == 1) {
            $InitializeCommonEvent(0, 90085002, 701, 8477, 8476, 1045390290, 1045395290, 1045390290, 1045390291, 1045390292, 1045390293, 20026);
        }
        $InitializeCommonEvent(0, 90085016, 701, 8477, 8476, 1045390290, 1045395290, 1020, 0);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90015000, 8476, 1045390290, 912000080, 30, 0, 8477);
            $InitializeCommonEvent(0, 99055500, 1045390290, 15);
        }
        if (1 != 1) {
            $InitializeCommonEvent(0, 90015000, 8476, 1045395290, 912000080, 30, 0, 8477);
            $InitializeCommonEvent(0, 99055500, 1045395290, 15);
        }
        $InitializeCommonEvent(0, 90015030, 0, 1045395290, 30, 920630, 8477);
    }
    if (MissionActive(701)) {
        $InitializeCommonEvent(0, 90085030, 701, 1045390296);
        $InitializeCommonEvent(0, 90085032, 701, 1045396295);
        $InitializeCommonEvent(0, 90015316, 1045392291);
    }
    $InitializeEvent(0, 1045392910);
    $InitializeEvent(0, 1045392800, 1045392500);
    $InitializeCommonEvent(0, 90085612, 602, Hero.Revenant, 9246, 9226, 1045390290, 8461);
    if (1 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9236, 9226, 9226, 1045395290, 1045390291, 0, 0, 0, 20026);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9236, 9226, 9226, 1045395290, 1045390291, 1045390292, 0, 0, 20026);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9236, 9226, 9226, 1045395290, 1045390291, 1045390292, 1045390293, 0, 20026);
    }
    if (4 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9236, 9226, 9226, 1045395290, 1045390291, 1045390292, 1045390293, 1045390294, 20026);
    }
    $InitializeCommonEvent(0, 90085613, 602, 9236, 9226, 9226, 1045395290);
    $InitializeCommonEvent(0, 90085614, 602, 9236, 1045396290, 1045390290, 8461);
});

$Event(1045392800, Restart, function(areaEntityId) {
    DisableNetworkSync();
    WaitFor(InArea(20000, areaEntityId));
    SetSpEffect(20000, 99215);
    RestartEvent();
});

$Event(1045392910, Restart, function() {
    WaitFor(SmallBaseAttached(1045392999, 30300000));
    EnableAsset(1045391900);
});
