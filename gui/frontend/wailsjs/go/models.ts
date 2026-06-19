export namespace main {
	
	export class ArgData {
	    label: string;
	    default: string;
	    filePicker: boolean;
	    dirPicker: boolean;
	    multiFile: boolean;
	
	    static createFrom(source: any = {}) {
	        return new ArgData(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.label = source["label"];
	        this.default = source["default"];
	        this.filePicker = source["filePicker"];
	        this.dirPicker = source["dirPicker"];
	        this.multiFile = source["multiFile"];
	    }
	}
	export class ScriptData {
	    name: string;
	    description: string;
	    help: string;
	    interactive: boolean;
	    argDefs: ArgData[];
	
	    static createFrom(source: any = {}) {
	        return new ScriptData(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.description = source["description"];
	        this.help = source["help"];
	        this.interactive = source["interactive"];
	        this.argDefs = this.convertValues(source["argDefs"], ArgData);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class GroupData {
	    name: string;
	    scripts: ScriptData[];
	
	    static createFrom(source: any = {}) {
	        return new GroupData(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.scripts = this.convertValues(source["scripts"], ScriptData);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class RunResult {
	    output: string;
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new RunResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.output = source["output"];
	        this.error = source["error"];
	    }
	}

}

