import {JobStatus,CaseStatus} from '../../constants/enums.js';
import {esc} from '../../utils/dom.js';
export const status=(v,labels=JobStatus)=>'<span class="status '+esc(v)+'">'+esc(labels[v]||v)+'</span>';
